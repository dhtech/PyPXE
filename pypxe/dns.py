# Attribution: https://gist.github.com/andreif/6069838
# coding=utf-8
import abc
import SocketServer
from dnslib import *


TTL = 60


class DomainName(str):
  def __getattr__(self, item):
    return DomainName(item + '.' + self)


class RequestHandler(SocketServer.BaseRequestHandler):

  def get_data(self):
    return self.request[0]

  def send_data(self, data):
    return self.request[1].sendto(data, self.client_address)

  def handle(self):
    self.server.logger.info(
        '%s request from (%s %s)', self.__class__.__name__[:3],
        self.client_address[0], self.client_address[1])
    try:
      data = self.get_data()
      self.send_data(self.dns_response(data))
    except Exception:
      self.server.logger.exception('Failed to parse request')

  def dns_response(self, data):
    request = DNSRecord.parse(data)

    reply = DNSRecord(DNSHeader(id=request.header.id, qr=1, aa=1, ra=1), q=request.q)

    qname = request.q.qname
    qn = str(qname)
    qtype = request.q.qtype
    qt = QTYPE[qtype]

    for rdata in self.server.lookup(qt, qn):
      self.server.logger.info(
          'Answering request for %s %s with %s', qt, qn, rdata)
      rqt = rdata.__class__.__name__
      if qt in ['*', rqt]:
        reply.add_answer(RR(
          rname=qname, rtype=getattr(QTYPE, rqt),
          rclass=1, ttl=TTL, rdata=rdata))

    return reply.pack()


class AbstractDNSD(object):

  __metaclass__ = abc.ABCMeta

  def __init__(self, ip, logger):
    self.ip = ip
    self.logger = logger

  def listen(self):
    s = SocketServer.ThreadingUDPServer((self.ip, 53), RequestHandler)
    s.logger = self.logger
    s.lookup = self.lookup
    s.serve_forever()

  @abc.abstractmethod
  def lookup(self, qtype, domain):
    pass
