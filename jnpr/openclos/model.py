'''
Created on Jul 8, 2014

@author: moloyc

'''
import uuid
import math
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, Enum, BLOB, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship, backref
from netaddr import IPAddress, IPNetwork, AddrFormatError
from crypt import Cryptic
Base = declarative_base()

class ManagedElement(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    def __str__(self):
        return str(self.__dict__)
    def __repr__(self):
        return self.__str__()
    @staticmethod
    def validateEnum(enumName, value, enumList):
        # Validate enumerated value, a restriction on string.
        error = False
        if isinstance(value, list):
            error = set(value) - set(enumList)
        else:
            error = value not in enumList
        if error:
            raise ValueError("%s('%s') must be one of %s" % (enumName, value, enumList))
    
class Pod(ManagedElement, Base):
    __tablename__ = 'pod'
    id = Column(String(60), primary_key=True)
    name = Column(String(100))
    description = Column(String(256))
    spineCount = Column(Integer)
    spineDeviceType = Column(String(100))
    leafUplinkcountMustBeUp = Column(Integer)
    leafCount = Column(Integer)
    leafDeviceType = Column(String(100))
    hostOrVmCountPerLeaf = Column(Integer)
    interConnectPrefix = Column(String(32))
    vlanPrefix = Column(String(32))
    loopbackPrefix = Column(String(32))
    managementPrefix = Column(String(32))
    spineAS = Column(Integer)
    leafAS = Column(Integer)
    topologyType = Column(Enum('threeStage', 'fiveStageRealEstate', 'fiveStagePerformance'))
    outOfBandAddressList = Column(String(512))  # comma separated values
    outOfBandGateway =  Column(String(32))
    spineJunosImage = Column(String(126))
    leafJunosImage = Column(String(126))
    allocatedInterConnectBlock = Column(String(32))
    allocatedIrbBlock = Column(String(32))
    allocatedLoopbackBlock = Column(String(32))
    allocatedSpineAS = Column(Integer)
    allocatefLeafAS = Column(Integer)
    inventoryData = Column(String(2048))
    leafGenericConfig = Column(BLOB)
    state = Column(Enum('unknown', 'created', 'updated', 'cablingDone', 'deviceConfigDone', 'ztpConfigDone', 'deployed', 'L2Verified', 'L3Verified'))
    encryptedPassword = Column(String(100)) # 2-way encrypted
    cryptic = Cryptic()
        
    def __init__(self, name, podDict):
        '''
        Creates a Pod object from dict, if following fields are missing, it throws ValueError
        interConnectPrefix, vlanPrefix, loopbackPrefix, spineAS, leafAS
        '''
        super(Pod, self).__init__(**podDict)
        self.update(None, name, podDict)
        
    def update(self, id, name, podDict):
        '''
        Updates a Pod ORM object from dict, it updates only following fields.
        spineCount, leafCount
        '''
        if id is not None:
            self.id = id
        elif 'id' in podDict:
            self.id = podDict.get('id')
        else:
            self.id = str(uuid.uuid4())
        
        if name is not None:
            self.name = name
        elif 'name' in podDict:
            self.name = podDict.get('name')
        
        self.description = podDict.get('description')
        self.spineCount = podDict.get('spineCount')
        self.spineDeviceType = podDict.get('spineDeviceType')
        self.leafCount = podDict.get('leafCount')
        self.leafDeviceType = podDict.get('leafDeviceType')
        self.leafUplinkcountMustBeUp = podDict.get('leafUplinkcountMustBeUp')
        if self.leafUplinkcountMustBeUp is None:
            self.leafUplinkcountMustBeUp = 2
        self.hostOrVmCountPerLeaf = podDict.get('hostOrVmCountPerLeaf')
        self.interConnectPrefix = podDict.get('interConnectPrefix')
        self.vlanPrefix = podDict.get('vlanPrefix')
        self.loopbackPrefix = podDict.get('loopbackPrefix')
        self.managementPrefix = podDict.get('managementPrefix')
        spineAS = podDict.get('spineAS')
        if spineAS is not None:
            self.spineAS = int(spineAS)
        leafAS = podDict.get('leafAS')
        if leafAS is not None:
            self.leafAS = int(leafAS)
        self.topologyType = podDict.get('topologyType')
        
        outOfBandAddressList = podDict.get('outOfBandAddressList')
        if outOfBandAddressList is not None and len(outOfBandAddressList) > 0:
            addressList = []
            if isinstance(outOfBandAddressList, list) == True:
                addressList = outOfBandAddressList
            else:
                addressList.append(outOfBandAddressList)
            self.outOfBandAddressList = ','.join(addressList)
        self.outOfBandGateway = podDict.get('outOfBandGateway')
        self.spineJunosImage = podDict.get('spineJunosImage')
        self.leafJunosImage = podDict.get('leafJunosImage')
            
        devicePassword = podDict.get('devicePassword')
        if devicePassword is not None and len(devicePassword) > 0:
            self.encryptedPassword = self.cryptic.encrypt(devicePassword)
            
        if self.state is None:
            self.state = 'unknown'

    def calculateEffectiveLeafUplinkcountMustBeUp(self):
        # if user configured a value, use it always 
        if self.leafUplinkcountMustBeUp is not None and self.leafUplinkcountMustBeUp > 0:
            return self.leafUplinkcountMustBeUp

        deployedSpines = 0
        for device in self.devices:
            if device.role == 'spine' and device.deployStatus == 'deploy':
                deployedSpines += 1
                
        count = int(math.ceil(float(deployedSpines)/2))
        if count < 2:
            count = 2

        return count
        
    def getCleartextPassword(self):
        '''
        Return decrypted password
        '''
        if self.encryptedPassword is not None and len(self.encryptedPassword) > 0:
            return self.cryptic.decrypt(self.encryptedPassword)
        else:
            return None
            
    def getHashPassword(self):
        '''
        Return hashed password
        '''
        cleartext = self.getCleartextPassword()
        if cleartext is not None:
            return self.cryptic.hashify(cleartext)
        else:
            return None
            
    '''
    Additional validations - 
    1. Spine ASN less then leaf ASN
    2. Add range check
    '''        
    def validate(self):
        self.validateRequiredFields()
        self.validateIPaddr()  
        if self.leafUplinkcountMustBeUp < 2 or self.leafUplinkcountMustBeUp > self.spineCount:
            raise ValueError('leafUplinkcountMustBeUp(%s) should be between 2 and spineCount(%s)' \
                % (self.leafUplinkcountMustBeUp, self.spineCount))
        
    def validateRequiredFields(self):
        
        error = ''
        if self.spineCount is None:
            error += 'spineCount, '
        if self.spineDeviceType is None:
            error += 'spineDeviceType, '
        if self.leafCount is None:
            error += 'leafCount, '
        if self.leafDeviceType is None:
            error += 'leafDeviceType, '
        if self.hostOrVmCountPerLeaf is None:
            error += 'hostOrVmCountPerLeaf, '
        if self.interConnectPrefix is None:
            error += 'interConnectPrefix, '
        if self.vlanPrefix is None:
            error += 'vlanPrefix, '
        if self.loopbackPrefix is None:
            error += 'loopbackPrefix, '
        if self.managementPrefix is None:
            error += 'managementPrefix, '
        if self.spineAS is None:
            error += 'spineAS, '
        if self.leafAS is None:
            error += 'leafAS, '
        if self.topologyType is None:
            error += 'topologyType, '
        if self.encryptedPassword is None:
            error += 'devicePassword'
        if error != '':
            raise ValueError('Missing required fields: ' + error)
        
    def validateIPaddr(self):   
        error = ''     
 
        try:
            IPNetwork(self.interConnectPrefix)  
        except AddrFormatError:
                error += 'interConnectPrefix, ' 
        try:
            IPNetwork(self.vlanPrefix)  
        except AddrFormatError:
                error += 'vlanPrefix, '
        try:
            IPNetwork(self.loopbackPrefix)  
        except AddrFormatError:
                error += 'loopbackPrefix'
        try:
            IPNetwork(self.managementPrefix)  
        except AddrFormatError:
                error += 'managementPrefix'
        if error != '':
            raise ValueError('invalid IP format: ' + error)
        
class Device(ManagedElement, Base):
    __tablename__ = 'device'
    id = Column(String(60), primary_key=True)
    name = Column(String(100))
    username = Column(String(100))
    encryptedPassword = Column(String(100)) # 2-way encrypted
    role = Column(String(32))
    macAddress = Column(String(32))
    managementIp = Column(String(32))
    family = Column(String(100))
    asn = Column(Integer)
    l2Status = Column(Enum('unknown', 'processing', 'good', 'error'), default = 'unknown')
    l2StatusReason = Column(String(256)) # will be populated only when status is error
    l3Status = Column(Enum('unknown', 'processing', 'good', 'error'), default = 'unknown')
    l3StatusReason = Column(String(256)) # will be populated only when status is error
    configStatus = Column(Enum('unknown', 'processing', 'good', 'error'), default = 'unknown')
    configStatusReason = Column(String(256)) # will be populated only when status is error
    config = Column(BLOB)
    pod_id = Column(String(60), ForeignKey('pod.id'), nullable = False)
    pod = relationship("Pod", backref=backref('devices', order_by=name, cascade='all, delete, delete-orphan'))
    deployStatus = Column(Enum('deploy', 'provision'), default = 'deploy')
    cryptic = Cryptic()
                
    def __init__(self, name, family, username, password, role, macAddress, managementIp, pod, deployStatus='deploy'):
        '''
        Creates Device object.
        '''
        self.id = str(uuid.uuid4())
        self.name = name
        self.family = family
        self.username = username
        if password is not None and len(password) > 0:
            self.encryptedPassword = self.cryptic.encrypt(password)
        self.role = role
        self.macAddress = macAddress
        self.managementIp = managementIp
        self.pod = pod
        self.deployStatus = deployStatus
        
    def update(self, name, username, password, macAddress, deployStatus='deploy'):
        '''
        Updates Device object.
        '''
        self.name = name
        self.username = username
        if password is not None and len(password) > 0:
            self.encryptedPassword = self.cryptic.encrypt(password)
        self.macAddress = macAddress
        self.deployStatus = deployStatus
        for interface in self.interfaces:
            interface.deployStatus = deployStatus
    
    def getCleartextPassword(self):
        '''
        Return decrypted password
        '''
        if self.encryptedPassword is not None and len(self.encryptedPassword) > 0:
            return self.cryptic.decrypt(self.encryptedPassword)
        else:
            return self.pod.getCleartextPassword()
            
    def getHashPassword(self):
        '''
        Return hashed password
        '''
        cleartext = self.getCleartextPassword()
        if cleartext is not None:
            return self.cryptic.hashify(cleartext)
        else:
            return None
            
class Interface(ManagedElement, Base):
    __tablename__ = 'interface'
    id = Column(String(60), primary_key=True)
    # getting list of interface order by name returns 
    # et-0/0/0, et-0/0/1, et-0/0/11, et/0/0/12, to fix this sequencing
    # adding order_number, so that the list would be et-0/0/0, et-0/0/1, et-0/0/2, et/0/0/3    
    name = Column(String(100))
    name_order_num = Column(Integer)
    type = Column(String(100))
    device_id = Column(String(60), ForeignKey('device.id'), nullable = False)
    device = relationship("Device",backref=backref('interfaces', order_by=name, cascade='all, delete, delete-orphan'))
    peer_id = Column(String(60), ForeignKey('interface.id'))
    peer = relationship('Interface', foreign_keys=[peer_id], uselist=False, post_update=True, )
    layer_below_id = Column(String(60), ForeignKey('interface.id'))
    layerAboves = relationship('Interface', foreign_keys=[layer_below_id])
    deployStatus = Column(Enum('deploy', 'provision'), default = 'deploy')
    __table_args__ = (
        UniqueConstraint('device_id', 'name', name='_device_id_name_uc'),
        UniqueConstraint('device_id', 'name_order_num', name='_device_id_name_order_num_uc'),
    )

    __mapper_args__ = {
        'polymorphic_identity':'interface',
        'polymorphic_on':type
    }
        
    def __init__(self, name, device, deployStatus='deploy'):
        self.id = str(uuid.uuid4())
        self.name = name
        self.device = device
        
        if name.count('/') == 3:
            self.name_order_num = 0
            nameSplit = name.split('/') 
            fpc = nameSplit[-3]
            pic = nameSplit[-2]
            port = nameSplit[-1]
            if fpc.isdigit():
                self.name_order_num += int(fpc) * 10000
            if pic.isdigit():
                self.name_order_num += int(pic) * 100
            if port.isdigit():
                self.name_order_num += int(port)
        self.deployStatus = deployStatus
        
class InterfaceLogical(Interface):
    __tablename__ = 'IFL'
    id = Column(String(60), ForeignKey('interface.id' ), primary_key=True)
    ipaddress = Column(String(40))
    mtu = Column(Integer)
    
    __mapper_args__ = {
        'polymorphic_identity':'logical',
    }
    
    def __init__(self, name, device, ipaddress=None, mtu=0, deployStatus='deploy'):
        '''
        Creates Logical Interface object.
        ipaddress is optional so that it can be allocated later
        mtu is optional, default value is taken from global setting
        '''
        super(InterfaceLogical, self).__init__(name, device, deployStatus)
        self.ipaddress = ipaddress
        self.mtu = mtu

class InterfaceDefinition(Interface):
    __tablename__ = 'IFD'
    id = Column(String(60), ForeignKey('interface.id' ), primary_key=True)
    role = Column(String(60))
    mtu = Column(Integer)
    lldpStatus = Column(Enum('unknown', 'good', 'error'), default = 'unknown') 
        
    __mapper_args__ = {
        'polymorphic_identity':'physical',
    }

    def __init__(self, name, device, role, mtu=0, deployStatus='deploy'):
        super(InterfaceDefinition, self).__init__(name, device, deployStatus)
        self.mtu = mtu
        self.role = role
        
class AdditionalLink(ManagedElement, Base):
    __tablename__ = 'additionalLink'
    id = Column(String(60), primary_key=True)
    device1 = Column(String(60)) # free form in case device does not exist in device table
    port1 = Column(String(100))
    device2 = Column(String(60)) # free form in case device does not exist in device table
    port2 = Column(String(100))
    lldpStatus = Column(Enum('unknown', 'good', 'error'), default = 'unknown') 
    __table_args__ = (
        UniqueConstraint('device1', 'port1', 'device2', 'port2', name='_device1_port1_device2_port2_uc'),
    )
        
    def __init__(self, device1, port1, device2, port2, lldpStatus='unknown'):
        self.id = str(uuid.uuid4())
        self.device1 = device1
        self.port1 = port1
        self.device2 = device2
        self.port2 = port2
        self.lldpStatus = lldpStatus
