'''

This file contains classes and functions that implement the PyPXE TFTP service

'''

import abc
import socket
import struct
import os
import select
import time
import logging
import math

class ParentSocket(socket.socket):
    '''Subclassed socket.socket to enable a link-back to the client object.'''
    parent = None


class AbstractClient(object):
    '''Client instance for TFTPD.'''

    __metaclass__ = abc.ABCMeta

    def __init__(self, mainsock, parent):

        self.default_retries = parent.default_retries
        self.timeout = parent.timeout
        self.ip = parent.ip
        self.message, self.address = mainsock.recvfrom(1024)
        self.logger = parent.logger.getChild('Client.{0}'.format(self.address))
        self.logger.debug('Recieving request...')
        self.retries = self.default_retries
        self.block = 1
        self.blksize = 512
        self.sent_time = float('inf')
        self.dead = False
        self.wrap = 0
        self.filesize = 0
        self.filename = ''

    def ready(self):
        '''Called when there is something to be read on our socket.'''
        self.message = self.sock.recv(1024)
        self.handle()

    @abc.abstractmethod
    def next_block(self):
        '''Return the next block to send to the client.'''
        pass

    def send_block(self):
        '''
            Sends the next block of data, setting the timeout and retry
            variables accordingly.
        '''
        block = self.next_block()
        if block is None:
          self.logger.debug('Got empty block, ignoring')
          return
        # opcode 3 == DATA, wraparound block number
        response = struct.pack('!HH', 3, self.block % 65536)
        response += block
        self.sock.sendto(response, self.address)
        self.logger.debug('Sending block {0}'.format(self.block))
        self.retries -= 1
        self.sent_time = time.time()

    def no_ack(self):
        '''Determines if we timed out waiting for an ACK from the client.'''
        if self.sent_time + self.timeout < time.time():
            return True
        return False

    def no_retries(self):
        '''Determines if the client ran out of retry attempts.'''
        if not self.retries:
            return True
        return False

    def valid_mode(self):
        '''Determines if the file read mode octet; if not, send an error.'''
        mode = self.message.split(chr(0))[1]
        if mode == 'octet': return True
        self.send_error(5, 'Mode {0} not supported'.format(mode))
        return False

    @abc.abstractmethod
    def check_file(self, filename):
        '''
            Determines if the file exist and if it is a file; if not,
            send an error.
        '''
        pass

    def validate_file(self):
        '''Sets the filename property if the filename is valid.'''
        filename = self.message.split(chr(0))[0]
        if self.check_file(filename):
            self.filename = filename
            return True
        self.send_error(1, 'File Not Found', filename = filename)
        return False

    def parse_options(self):
        '''
            Extracts the options sent from a client; if any, calculates the last
            block based on the filesize and blocksize.
        '''
        options = self.message.split(chr(0))[2: -1]
        options = dict(zip(options[0::2], map(int, options[1::2])))
        self.blksize = options.get('blksize', self.blksize)
        self.lastblock = math.ceil(self.filesize / float(self.blksize))
        self.tsize = True if 'tsize' in options else False
        if self.filesize > (2 ** 16) * self.blksize:
            self.logger.warning('Request too big, attempting transfer anyway.')
            self.logger.debug('Details: Filesize {0} is too big for blksize {1}.'.format(self.filesize, self.blksize))

        if len(options):
            # we need to know later if we actually had any options
            self.block = 0
            return True
        else:
            return False

    def reply_options(self):
        '''Acknowledges any options received.'''
        # only called if options, so send them all
        response = struct.pack("!H", 6)

        response += 'blksize' + chr(0)
        response += str(self.blksize) + chr(0)
        response += 'tsize' + chr(0)
        response += str(self.filesize) + chr(0)

        self.sock.sendto(response, self.address)


    @abc.abstractmethod
    def prepare_request(self, filename):
      '''Do backend dependent actions to prepare for serving a file.'''
      # Implementations need to set self.filesize here
      pass

    def new_request(self):
        '''
            When receiving a read request from the parent socket, open our
            own socket and check the read request; if we don't have any options,
            send the first block.
        '''
        self.sock = ParentSocket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.ip, 0))
        # used by select() to find ready clients
        self.sock.parent = self

        if not self.valid_mode() or not self.validate_file():
            # some clients just ACK the error (wrong code?)
            # so forcefully shutdown
            self.complete()
            return

        self.logger.info('New request for "{0}"'.format(self.filename))
        self.prepare_request(self.filename)

        if not self.parse_options():
            # no options recieved so start transfer
            if self.block == 1:
                self.send_block()
            return

        # we got some options so ACK those first
        self.reply_options()

    def send_error(self, code = 1, message = 'File Not Found', filename = ''):
        '''
            Sends an error code and string to a client. See RFC1350, page 10 for
            details.

            Value   Meaning
            =====   =======
            0       Not defined, see error message (if any).
            1       File not found.
            2       Access violation.
            3       Disk full or allocation exceeded.
            4       Illegal TFTP operation.
            5       Unknown transfer ID.
            6       File already exists.
            7       No such user.
        '''
        response =  struct.pack('!H', 5) # error opcode
        response += struct.pack('!H', code) # error code
        response += message
        response += chr(0)
        self.sock.sendto(response, self.address)
        self.logger.error('Sending {0}: {1} {2}'.format(code, message, filename))

    def complete(self):
        '''
            Closes the socket after sending it
            and marks ourselves as dead to be cleaned up.
        '''
        self.sock.close()
        self.dead = True

    def handle(self):
        '''Takes the message from the parent socket and act accordingly.'''
        # if addr not in ongoing, call this, else ready()
        [opcode] = struct.unpack('!H', self.message[:2])
        if opcode == 1:
            self.message = self.message[2:]
            self.new_request()
        elif opcode == 4:
            [block] = struct.unpack('!H', self.message[2:4])
            if block == 0:
                self.wrap += 1
            if block < self.block % 65536:
                self.logger.warning('Ignoring duplicated ACK received for block {0}'.format(self.block))
            elif block > self.block % 65536:
                self.logger.warning('Ignoring out of sequence ACK received for block {0}'.format(self.block))
            elif block + self.wrap * 65536 == self.lastblock:
                if self.filesize % self.blksize == 0:
                    self.block = block + 1
                    self.send_block()
                self.logger.info('Completed sending "{0}"'.format(self.filename))
                self.complete()
            else:
                self.block = block + 1
                self.retries = self.default_retries
                self.send_block()


class FileBackedClient(AbstractClient):
    '''Client instance backed with local filesystem.'''

    def __init__(self, mainsock, parent):
        super(FileBackedClient, self).__init__(mainsock, parent)
        self.fh = None

    def check_file(self, filename):
        '''
            Determines if the file exist and if it is a file; if not,
            send an error.
        '''
        if os.path.lexists(filename) and os.path.isfile(filename):
            return True
        return False

    def complete(self):
        '''Closes a file after sending it.'''
        super(FileBackedClient, self).complete()
        if self.fh is None:
          return
        self.fh.close()

    def next_block(self):
        '''Return the next block to send to the client.'''
        if self.fh is None:
          return None
        return self.fh.read(self.blksize)

    def prepare_request(self, filename):
        '''Open file handler in preparation for serving the file.'''
        self.fh = open(self.filename, 'rb')
        self.filesize = os.path.getsize(self.filename)


class BaseTFTPD(object):
    '''
        This class implements a read-only TFTP server
        implemented from RFC1350 and RFC2348
    '''
    def __init__(self, client_cls, **server_settings):
        self.ip = server_settings.get('ip', '0.0.0.0')
        self.port = server_settings.get('port', 69)
        self.mode_debug = server_settings.get('mode_debug', False) # debug mode
        self.logger = server_settings.get('logger', None)
        self.default_retries = server_settings.get('default_retries', 3)
        self.timeout = server_settings.get('timeout', 5)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.ip, self.port))
        self.client_cls = client_cls

        # setup logger
        if self.logger == None:
            self.logger = logging.getLogger('TFTP')
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        if self.mode_debug:
            self.logger.setLevel(logging.DEBUG)

        self.logger.debug('NOTICE: TFTP server started in debug mode. TFTP server is using the following:')
        self.logger.debug('Server IP: {0}'.format(self.ip))
        self.logger.debug('Server Port: {0}'.format(self.port))

        self.ongoing = []


    def listen(self):
        '''This method listens for incoming requests.'''
        while True:
            try:
                # remove complete clients to select doesn't fail
                map(self.ongoing.remove, [client for client in self.ongoing if client.dead])
                rlist, _, _ = select.select([self.sock] + [client.sock for client in self.ongoing if not client.dead], [], [], 0)
                for sock in rlist:
                    if sock == self.sock:
                        # main socket, so new client
                        client = self.client_cls(sock, self)
                        self.ongoing.append(client)
                        client.handle()
                    else:
                        # client socket, so tell the client object it's ready
                        sock.parent.ready()
                # if we haven't recieved an ACK in timeout time, retry
                [client.send_block() for client in self.ongoing if client.no_ack()]
                # if we have run out of retries, kill the client
                [client.complete() for client in self.ongoing if client.no_retries()]
            except:
                self.logger.exception('listen loop exception')


class TFTPD(BaseTFTPD):
    '''
        Implemention of TFTP class with local filesystem as backing storage.
    '''
    def __init__(self, **server_settings):
        super(TFTPD, self).__init__(FileBackedClient, **server_settings)
        self.netbook_directory = server_settings.get('netbook_directory', '.')
        self.logger.debug('Network Boot Directory: {0}'.format(self.netbook_directory))

        # start in network boot file directory and then chroot,
        # this simplifies target later as well as offers a slight security increase
        os.chdir (self.netbook_directory)
        os.chroot ('.')
