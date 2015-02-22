import os
import struct
import hashlib
import math
import attributes
from io import BytesIO
#All the following functions are individually defined
#in RFC5661 sections 18.*

#Operation ID for COMPOUND as per rFC5661-16.2.1
nfs_opnum4 = {}
nfs_opnum4_append = lambda f,x: nfs_opnum4.__setitem__(x,f)

#Functions all accept request and response strings, and state dict
#They MUST cleanup the request string themselves (chop off the start)

def ACCESS(request, response, state):
    #THIS IS NOT COMPLETE
    #RELIES ON AUTHENTICATION WHICH IS NOT YET DONE
    [access] = struct.unpack("!I", request.read(4))

    path = state["globals"]["fhs"][state["current"]["fh"]]
    pathstat = os.lstat(path)
    result = 0
    if pathstat.st_uid == state["auth"]["uid"]:
        #user
        #Read
        result |= (0x1|0x2) if pathstat.st_mode&256 else 0
        #Write
        if not state["globals"]["readonly"]:
            result |= (0x4|0x8) if pathstat.st_mode&128 else 0
        #Exec
        result |= 0x20 if pathstat.st_mode&64 else 0
    elif pathstat.st_gid == state["auth"]["uid"]:
        #group
        #if group and user, user's lack of permissions win
        #Read
        result |= (0x1|0x2) if pathstat.st_mode&32 else 0
        #Write
        if not state["globals"]["readonly"]:
            result |= (0x4|0x8) if pathstat.st_mode&16 else 0
        #Exec
        result |= 0x20 if pathstat.st_mode&8 else 0
    else:
        #all
        #Read
        result |= (0x1|0x2) if pathstat.st_mode&4 else 0
        #Write
        if not state["globals"]["readonly"]:
            result |= (0x4|0x8) if pathstat.st_mode&2 else 0
        #Exec
        result |= 0x20 if pathstat.st_mode&1 else 0
    #os sep
    #parent directory stat
    #Delete requires write on the parent directory
    if not state["globals"]["readonly"]:
        if not path == state["globals"]["root"]:
            ppathstat = os.lstat('/'.join(path.split("/")[:-1])).st_mode
            if pathstat.st_uid == state["auth"]["uid"]:
                result |= 0x10 if ppathstat&128 else 0
            elif pathstat.st_gid == state["auth"]["uid"]:
                result |= 0x10 if ppathstat&16 else 0
            else:
                result |= 0x10 if ppathstat&2 else 0
    if state["auth"]["uid"] == state["auth"]["gid"] == 0:
        if state["globals"]["readonly"]:
            result = 0x1|0x2|0x20
        else:
            result = 0x1|0x2|0x4|0x8|0x10|0x20

    #ACCESS, NFS4_OK
    response += struct.pack("!II", 3, 0)
    #Support all
    response += struct.pack("!II", access, result)
    return request, response
nfs_opnum4_append(ACCESS, 3)

def CLOSE(request, response, state):
    [seqid] = struct.unpack("!I", request.read(4))

    [stateidseqid] = struct.unpack("!I", request.read(4))

    stateid = request.read(12)

    #Remove the lock
    del state["globals"]["locks"][state["current"]["fh"]][stateid]

    #CLOSE, NFS4_OK
    response += struct.pack("!II", 4, 0)
    #Deprecated response of stateid
    response += struct.pack("!I", stateidseqid)
    response += stateid
    return request, response
nfs_opnum4_append(CLOSE, 4)

def COMMIT(request, response, state):
    #5
    return
nfs_opnum4_append(COMMIT, 5)

def CREATE(request, response, state):
    [ftype] = struct.unpack("!I", request.read(4))

    [namelen] = struct.unpack("!I", request.read(4))
    name = request.read(namelen)
    offset = 4 - (namelen % 4) if namelen % 4 else 0
    request.seek(offset, 1)
    if ftype == 5: #NF4LNK:
        names = [name]
        [namelen] = struct.unpack("!I", request.read(4))
        names.append(request.read(namelen))
        offset = 4 - (namelen % 4) if namelen % 4 else 0
        request.seek(offset, 1)

    #Attribute bitmask
    [attrlen] = struct.unpack("!I", request.read(4))
    attr_req = struct.unpack("!"+str(attrlen)+"I", request.read(attrlen*4))
    #Attribute arguments
    [attrslen] = struct.unpack("!I", request.read(4))
    attrs = request.read(attrslen)

    #CREATE, READ ONLY FILESYSTEM
    if state["globals"]["readonly"]:
        response += struct.pack("!II", 6, 30)
        return request, response

    return
nfs_opnum4_append(CREATE, 6)

def GETATTR(request, response, state):
    client = state['current']
    fh = client['fh']
    path = state['globals']['fhs'][fh]

    [maskcnt] = struct.unpack("!I", request.read(4))

    attr_req = struct.unpack("!"+str(maskcnt)+"I", request.read(4*maskcnt))

    if not os.path.lexists(path):
        #Here so we don't have to cleanup manually
        #NFS4ERR_NOENT
        response += struct.pack("!II", 9, 2)
        return request, response

    pathstat = os.lstat(path)
    attrib = attributes.ReadAttributes(fh, state, attr_req)

    #GETATTR, NFS4_OK
    response += struct.pack("!II", 9, 0)

    #response bitmask here
    response += attrib.respbitmask

    #byte length of attrlist
    response += struct.pack("!I", attrib.packedattrlen)
    #pre-packed attr_vals
    response += attrib.packedattr

    #return as LSB int32 array, attr_vals
    return request, response
nfs_opnum4_append(GETATTR, 9)

def GETFH(request, response, state):
    #128 byte fh ret
    #store, opaque to client, our job to translate
    client = state['current']
    #Get client's current fh (128 byte string)
    fh = client['fh']

    #GETFH, NFS4_OK
    response += struct.pack("!II", 10, 0)
    #Size of fh == NFS4_FHSIZE
    response += struct.pack("!I", 128)
    response += fh

    return request, response
nfs_opnum4_append(GETFH, 10)

def LOCK(request, response, state):
    #12
    return
nfs_opnum4_append(LOCK, 12)

def LOCKT(request, response, state):
    #13
    return
nfs_opnum4_append(LOCKT, 13)

def LOCKU(request, response, state):
    #14
    return
nfs_opnum4_append(LOCKU, 14)

def LOOKUP(request, response, state):
    client = state['current']
    error = 0

    [namelen] = struct.unpack("!I", request.read(4))

    name = request.read(namelen)
    offset = 4 - (namelen % 4) if namelen % 4 else 0
    request.seek(offset, 1)

    fh = client['fh']
    path = state["globals"]['fhs'][fh]
    if os.lstat(path).st_mode&61440 != 16384:
        #NFS4ERR_NOTDIR
        error = 20
    newpath = path+"/"+name
    if not os.path.lexists(newpath):
        #NFS4ERR_NOENT
        error = 2

    client['fh'] = hashlib.sha512(newpath).hexdigest()
    state["globals"]['fhs'][hashlib.sha512(newpath).hexdigest()] = newpath

    #LOOKUP
    response += struct.pack("!II", 15, error)
    return request, response
nfs_opnum4_append(LOOKUP, 15)

def LOOKUPP(request, response, state):
    #16
    return
nfs_opnum4_append(LOOKUPP, 16)

def NVERIFY(request, response, state):
    #17
    return
nfs_opnum4_append(NVERIFY, 17)

def OPEN(request, response, state):
    [seqid] = struct.unpack("!I", request.read(4))

    share_access, share_deny = struct.unpack("!II", request.read(8))

    clientid = request.read(8)

    [ownerlen] = struct.unpack("!I", request.read(4))

    owner = request.read(ownerlen)
    offset = 4 - (ownerlen % 4) if ownerlen % 4 else 0
    request.seek(offset, 1)

    [opentype] = struct.unpack("!I", request.read(4))
    if opentype:
        [createmode] = struct.unpack("!I", request.read(4))
        if createmode in (0,1):
            #UNCHECKED, GUARDED
            #1 = noclobber
            [attrlen] = struct.unpack("!I", request.read(4))
            attr = struct.unpack("!"+str(attrlen)+"I", request.read(4*attrlen))
            [tosetlen] = struct.unpack("!I", request.read(4))
            toset = request.read(tosetlen)
        if createmode == 3:
            #EXCLUSIVE4_1
            verifier = request.read(8)
            #UNKNOWN OPAQUE DATA
            #Wireshark doesn't tag it
            #Without this we crash
            request.read(12)

    [openclaim] = struct.unpack("!I", request.read(4))

    if openclaim == 0:
        [claimlen] = struct.unpack("!I", request.read(4))
        claimname = request.read(claimlen)
        offset = 4 - (claimlen % 4) if claimlen % 4 else 0
        request.seek(offset, 1)
        #The following makes the file exist
        path = state["globals"]['fhs'][state['current']['fh']]
        state["globals"]['fhs'][hashlib.sha512(path+"/"+claimname).hexdigest()] = path+"/"+claimname
        fh = hashlib.sha512(path+"/"+claimname).hexdigest()
        #pathsep
        #opentype evaluated to Shortcircuit
        if not os.path.lexists(path+"/"+claimname) and (opentype and createmode != 4):
            open(path+"/"+claimname,"w").close()
            print path+"/"+claimname
    elif openclaim == 1:
        [delegate_type] = struct.unpack("!I", request.read(4))
        if state["globals"]["readonly"]:
            #OPEN, READONLY
            response += struct.pack("!II", 18, 30)
            return request, response

    if opentype and createmode in (0, 1):
        #Recreate the request for proper parsing
        #probably ought to modify the if opentype above
        req = struct.pack("!I", attrlen)
        req += struct.pack("!"+str(attrlen)+"I", *attr)
        req += struct.pack("!I", tosetlen)
        req += toset
        attrib = attributes.WriteAttributes(fh, state, BytesIO(req))

    #OPEN
    response += struct.pack("!II", 18, 0)

    #stateid seqid
    response += struct.pack("!I", 1)
    #random stateid is used for keeping track of locks
    stateid = os.urandom(12)
    response += stateid
    if state[clientid]['fh'] not in state["globals"]['locks']:
        state["globals"]['locks'][state[clientid]['fh']] = {stateid:(share_access, share_deny)}
    else:
        state["globals"]['locks'][state[clientid]['fh']][stateid] = (share_access, share_deny)

    #change_info
    response += struct.pack("!IQQ", 0, 0, 0)

    #rflags, matches kernel
    response += struct.pack("!I", 0)

    #Applied Attributes
    if not opentype:
        response += struct.pack("!I", 0)
    elif createmode in (0, 1):
        response += attrib.respbitmask

    #OPEN_DELEGATE_NONE
    response += struct.pack("!I", 0)

    return request, response
nfs_opnum4_append(OPEN, 18)

def OPEN_DOWNGRADE(request, response, state):
    #21
    return
nfs_opnum4_append(OPEN_DOWNGRADE, 21)

def PUTFH(request, response, state):
    [length] = struct.unpack("!I", request.read(4)) #should always be 128
    fh = request.read(length)
    try:
        path = state["globals"]['fhs'][fh]
    except KeyError:
        #PUTFH, NFS4ERR_STALE
        response += struct.pack("!II", 22, 70)
        return request, response
    state['current']['fh'] = fh
    print state["globals"]["fhs"][fh], fh

    #PUTFH, OK
    response += struct.pack("!II", 22, 0)
    return request, response
nfs_opnum4_append(PUTFH, 22)

def PUTPUBFH(request, response, state):
    #23
    return
nfs_opnum4_append(PUTPUBFH, 23)

def PUTROOTFH(request, response, state):
    '''
    Takes no arguments
    returns root filehandle.
    '''
    #sha512 is free 128 byte
    nfsroot = hashlib.sha512(state["globals"]["root"]).hexdigest()
    state['current']['fh'] = nfsroot
    state["globals"]['fhs'][nfsroot] = state["globals"]["root"]

    #PUTROOTFH, OK
    response += struct.pack("!II", 24, 0)

    return request, response
nfs_opnum4_append(PUTROOTFH, 24)

def READ(request, response, state):
    [seqid] = struct.unpack("!I", request.read(4))

    stateid = request.read(12)

    [offset, count] = struct.unpack("!QI", request.read(12))

    #need to check lock here
    client = state["current"]
    fh = client["fh"]
    path = state["globals"]["fhs"][fh]
    locks = state["globals"]["locks"][fh]

    #implicit read only
    file = open(path)
    file.seek(offset)
    data = file.read(count)
    #Go to EOF
    file.seek(0, 2)

    #READ, NFS4_OK
    response += struct.pack("!II", 25, 0)

    if offset+len(data) < file.tell():
        #Not EOF
        response += struct.pack("!I", 0)
    else:
        #EOF
        response += struct.pack("!I", 1)

    #Length of returned data
    response += struct.pack("!I", len(data))
    response += data

    #Pad to 4 bytes
    offset = 4 - (len(data) % 4) if len(data) % 4 else 0
    response += "\x00"*offset

    return request, response
nfs_opnum4_append(READ, 25)

def READDIR(request, response, state):
    #Lots here taken from GETATTR, we do the same mask business
    client = state['current']
    fh = client['fh']
    path = state["globals"]['fhs'][fh]

    #we modify later, so list
    reqcookie = list(struct.unpack("!II", request.read(8)))

    cookie_verf = struct.unpack("!II", request.read(8))

    [dircount, maxcount] = struct.unpack("!II", request.read(8))

    [maskcnt] = struct.unpack("!I", request.read(4))

    attr_req = struct.unpack("!"+str(maskcnt)+"I", request.read(4*maskcnt))

    #READDIR, NFS4_OK
    response += struct.pack("!II", 26, 0)

    #Verifier. Used for detecting stale cookies
    response += struct.pack("!II", len(os.listdir(path)), 1)

    eof = 1
    #skip those we've already seen. overly relies on os.listdir ordering
    dirents = list(enumerate(os.listdir(path)))
    if reqcookie[0]:
        dirents = dirents[reqcookie[0]+1:]
    for cookie, dirent in dirents:
        subresponse = ""
        #We have a value
        subresponse += struct.pack("!I", 1)
        #Cookieval
        subresponse += struct.pack("!II", cookie, 0)
        #Name 4byte padded
        subresponse += struct.pack("!I", len(dirent))
        subresponse += dirent
        offset = 4 - (len(dirent) % 4) if len(dirent) % 4 else 0
        subresponse += "\x00"*offset

        #Create a filehandle object
        #Probably ought to be pathsep
        state["globals"]['fhs'][hashlib.sha512(path+"/"+dirent).hexdigest()] = path+"/"+dirent
        attrib = attributes.ReadAttributes(hashlib.sha512(path+"/"+dirent).hexdigest(), state, attr_req)
        #Add in the attributes
        subresponse += attrib.respbitmask
        subresponse += struct.pack("!I", attrib.packedattrlen)
        subresponse += attrib.packedattr
        if not (maxcount - len(subresponse) > 0):
            eof = 0
            break
        else:
            response += subresponse
            maxcount -= len(subresponse)

    #value following?, EOF
    response += struct.pack("!II", 0, eof)

    return request, response
nfs_opnum4_append(READDIR, 26)

def READLINK(request, response, state):
    path = state["globals"]['fhs'][state['current']['fh']]
    if os.lstat(path).st_mode&61440 != 40960:
        #READLINK, NFS4ERR_WRONG_TYPE
        response += struct.pack("!II", 27, 10083)
        return request, response

    realpath = os.readlink(path)
    #READLINK, NFS4_OK
    response += struct.pack("!II", 27, 0)
    response += struct.pack("!I", len(realpath))
    response += realpath
    offset = 4 - (len(realpath) % 4) if len(realpath) % 4 else 0
    response += "\x00" * offset

    return request, response
nfs_opnum4_append(READLINK, 27)

def REMOVE(request, response, state):
    #28
    return
nfs_opnum4_append(REMOVE, 28)

def RENAME(request, response, state):
    #29
    return
nfs_opnum4_append(RENAME, 29)

def RESTOREFH(request, response, state):
    #31
    return
nfs_opnum4_append(RESTOREFH, 31)

def SAVEFH(request, response, state):
    #32
    return
nfs_opnum4_append(SAVEFH, 32)

def SECINFO(request, response, state):
    #33
    return
nfs_opnum4_append(SECINFO, 33)

def SETATTR(request, response, state):
    [seqid] = struct.unpack("!I", request.read(4))
    stateid = request.read(12)

    fh = state['current']['fh']

    [masklen] = struct.unpack("!I", request.read(4))
    request.read(masklen*4)
    [arglen] = struct.unpack("!I", request.read(4))
    #Makes it easier to create the object next
    request.seek(-(masklen*4+8), 1)

    if state["globals"]["readonly"]:
        #SETATTR, READONLY
        response += struct.pack("!II", 34, 30)
        return request, response

    #Masklen+arglen+8 is the total argument structure size
    attrib = attributes.WriteAttributes(fh, state, BytesIO(request.read(masklen*4+arglen+8)))

    #SETATTR, NFS4_OK
    response += struct.pack("!II", 34, 0)
    response += attrib.respbitmask

    return request, response
nfs_opnum4_append(SETATTR, 34)

def VERIFY(request, response, state):
    #37
    return
nfs_opnum4_append(VERIFY, 37)

def WRITE(request, response, state):
    [seqid] = struct.unpack("!I", request.read(4))
    stateid = request.read(12)
    [offset] = struct.unpack("!Q", request.read(8))
    [stable] = struct.unpack("!I", request.read(4))
    [datalen] = struct.unpack("!I", request.read(4))
    data = request.read(datalen)
    offset = 4 - (datalen % 4) if datalen % 4 else 0
    request.seek(offset, 1)

    if state["globals"]["readonly"]:
        #WRITE, READONLYFILESYSTEM
        response += struct.pack("!II", 38, 30)
        return request, response
    return
nfs_opnum4_append(WRITE, 38)

def BACKCHANNEL_CTL(request, response, state):
    #40
    return
nfs_opnum4_append(BACKCHANNEL_CTL, 40)

def BIND_CONN_TO_SESSION(request, response, state):
    #41
    return
nfs_opnum4_append(BIND_CONN_TO_SESSION, 41)

def EXCHANGE_ID(request, response, state):
    '''
    The client uses the EXCHANGE_ID operation to register a particular
    client owner with the server.  The client ID returned from this
    operation will be necessary for requests that create state on the
    server and will serve as a parent object to sessions created by the
    client.
        - RFC5661-18.35.3
    '''
    verifier = request.read(8) #RFC5661-3.1/2
    client = {}

    [client['owneridlen']] = struct.unpack("!I", request.read(4))
    client['ownerid'] = request.read(client['owneridlen'])
    #Pad to multiple of 4?
    offset = 4 - (client['owneridlen'] % 4) if client['owneridlen'] % 4 else 0
    request.seek(offset, 1)

    client['flags'] = struct.unpack("!I", request.read(4))
    client['stateprotection'] = struct.unpack("!I", request.read(4))

    [client['impl_id']] = struct.unpack("!I", request.read(4))

    [client['domainlen']] = struct.unpack("!I", request.read(4))
    client['domain'] = request.read(client['domainlen'])
    offset = 4 - (client['domainlen'] % 4) if client['domainlen'] % 4 else 0
    request.seek(offset,1)

    [client['namelen']] = struct.unpack("!I", request.read(4))
    client['name'] = request.read(client['namelen'])
    offset = 4 - (client['namelen'] % 4) if client['namelen'] % 4 else 0
    request.seek(offset,1)

    client['date'] = struct.unpack("!II", request.read(8))


    #EXCHANGE_ID, NFS4_OK
    response += struct.pack("!II", 42, 0)
    #clientid needs to be unique, 64 bit. RFC5661-2.4
    clientid = os.urandom(8)
    response += clientid
    #seqid, flags, state_protect
    response += struct.pack("!III", 0, 1<<16|1, 0)
    #minor id
    response += struct.pack("!d", 0)
    #major ID + padding (hardcoded)
    majorid = "PyPXE"
    response += struct.pack("!I", 5)
    response += majorid+"\x00\x00\x00"
    #scope
    response += struct.pack("!I", 5)
    response += majorid+"\x00\x00\x00"
    #eir_erver_impl_id
    response += struct.pack("!I", 0)

    #needed for caching
    #but don't ache this or CREATE_SESSION
    client['seqid'] = [0,None]
    client['clientid'] = clientid

    state[clientid] = client
    state["current"] = state[clientid]
    return request, response
nfs_opnum4_append(EXCHANGE_ID, 42)

def CREATE_SESSION(request, response, state):
    '''

    '''
    clientid = request.read(8)

    [sequenceid] = struct.unpack("!I", request.read(4))

    [flags] = struct.unpack("!I", request.read(4))

    fore_attrs = struct.unpack("!IIIIIII", request.read(28))
    back_attrs = struct.unpack("!IIIIIII", request.read(28))

    [callback] = struct.unpack("!I", request.read(4))

    #AUTH_SYS - THIS MAY BREAK
    [unknown, flavor, stamp] = struct.unpack("!III", request.read(12))

    [machinelen] = struct.unpack("!I", request.read(4))
    machinename = request.read(machinelen)
    offset = 4 - (machinelen % 4) if machinelen % 4 else 0
    request.seek(offset, 1)

    [uid, gid] = struct.unpack("!II", request.read(8))

    error = 0
    if clientid not in state.keys():
        #NFS4ERR_STALE_CLIENTID
        error = 10022
        #Section 15.1
    elif sequenceid > state[clientid]['seqid'][0]+1:
        #NFS4ERR_SEQ_MISORDERED
        error = 10063


    #CREATE_SESSION, Error
    response += struct.pack("!II", 43, error)
    if error:
        response += struct.pack("!I", 0)
        return request, response

    sessid = os.urandom(16)

    state[clientid]['sessid'] = sessid

    response += sessid
    response += struct.pack("!I", sequenceid)
    #not CREATE_SESSION4_FLAG_PERSIST or CREATE_SESSION4_FLAG_CONN_BACK_CHAN
    response += struct.pack("!I", 0)
    response += struct.pack("!IIIIIII", *fore_attrs)
    response += struct.pack("!IIIIIII", *back_attrs)

    return request, response
nfs_opnum4_append(CREATE_SESSION, 43)

def DESTROY_SESSION(request, response, state):
    sessid = request.read(16)
    if state.keys() == ["globals"] or state["current"]["sessid"] == sessid:
        #We don't have the client id, or we have no state at all
        #Error badsession
        error = 10052
    else:
        clientid = state["current"]["clientid"]
        state[clientid]['sessid'] = ""
        error = 0
    #DESTROY_SESSION
    response += struct.pack("!II", 44, error)
    return request, response
nfs_opnum4_append(DESTROY_SESSION, 44)

def FREE_STATEID(request, response, state):
    #45
    return
nfs_opnum4_append(FREE_STATEID, 45)

def LAYOUTCOMMIT(request, response, state):
    #49
    return
nfs_opnum4_append(LAYOUTCOMMIT, 49)

def SECINFO_NO_NAME(request, response, state):
    [secinfostyle] = struct.unpack("!I", request.read(4))

    #SECINFO_NO_NAME, NFS4_OK
    response += struct.pack("!II", 52, 0)
    #flavor count
    response += struct.pack("!I", 1)
    #AUTH_UNIX
    response += struct.pack("!I", 1)
    return request, response
nfs_opnum4_append(SECINFO_NO_NAME, 52)

def SEQUENCE(request, response, state):
    '''
    The SEQUENCE operation is used by the server to implement session request
    control and the reply cache semantics.
        - RFC5661-18.46.3
    '''
    sessid = request.read(16)
    [seqid,
    slotid,
    highest_slotid,
    cachethis] = struct.unpack("!IIII", request.read(16))

    error = 0
    #We have no clients
    if state.keys() == ["globals", "auth"]:
        #NFS4ERR_STALE_CLIENTID
        #Goes back to EXCHANGE_ID (Not allowed in SEQUENCE)
        response += struct.pack("!II", 53, 10022)
        response += sessid
        response += struct.pack("!IIIII",
                seqid,
                slotid,
                32,
                32,
                0)
        return request, response
    elif ("current" in state and not state["current"]["sessid"] == sessid):
        #NFS4ERR_BADSESSION
        #Goes back to CREATE_SESSION (Not allowed in SEQUENCE)
        response += struct.pack("!II", 53, 10052)
        response += sessid
        response += struct.pack("!IIIII",
                seqid,
                slotid,
                32,
                32,
                0)
        return request, response
    else:
        try:
            clientid = state["current"]["clientid"]
        except:
            print state
            raise Exception("STATE ERROR - SEQUENCE")


    #Retry and cached?
    if seqid == state[clientid]['seqid'][0] and state[clientid]['seqid'][1]:
        return request, state[clientid]['seqid'][1]
    response += struct.pack("!II", 53, 0)
    response += sessid
    response += struct.pack("!IIIII",
            seqid,
            slotid,
            32,
            32,
            0)

    return request, response
nfs_opnum4_append(SEQUENCE, 53)

def SET_SSV(request, response, state):
    #54
    return
nfs_opnum4_append(SET_SSV, 54)

def TEST_STATEID(request, response, state):
    #We don't use these properly yet. Relates to locks.
    [num] = struct.unpack("!I", request.read(4))
    #4 byte seqid + 12 byte stateid
    stateids = request.read(num*16)

    #DESTROY_CLIENTID, NFS4_OK
    response += struct.pack("!II", 55, 0)
    response += struct.pack("!I", num)
    #NFS4_OK for each stateid
    response += struct.pack("!I", 0)*num
    return request, response
nfs_opnum4_append(TEST_STATEID, 55)

def DESTROY_CLIENTID(request, response, state):
    '''
    If there are sessions (both idle and non-idle), opens, locks, delegations,
    layouts, and/or wants (Section 18.49) associated with the unexpired lease of
    the client ID, the server MUST return NFS4ERR_CLIENTID_BUSY.
        - RFC5661-18.50.3
    '''
    clientid = request.read(8)
    try:
        del state[clientid]
        state["current"] = ""
    except:
        pass
    #DESTROY_CLIENTID, NFS4_OK
    response += struct.pack("!II", 57, 0)

    return request, response
nfs_opnum4_append(DESTROY_CLIENTID, 57)

def RECLAIM_COMPLETE(request, response, state):
    '''
    A RECLAIM_COMPLETE operation is used to indicate that the client has
    reclaimed all of the locking state that it will recover, when it is
    recovering state due to either a server restart or the transfer of a file
    system to another server.
        - RFC5661-18.51.3
    '''
    rca_one_fs = struct.unpack("!I", request.read(4))
    #Not using this (yet?)
    response += struct.pack("!II", 58, 0)
    response += struct.pack("!I", 0)

    return request, response
nfs_opnum4_append(RECLAIM_COMPLETE, 58)