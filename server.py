import dbus

from gobject import *
from dbus.mainloop.glib import DBusGMainLoop

class FlushDescr:
    def __init__(self, fd):
        self.fd = fd

    def open(self, *args, **kwargs):
        self.fd.open(*args, **kwargs)

    def write(self, *args, **kwargs):
        self.fd.write(*args, **kwargs)
        self.fd.flush()

    def read(self, *args, **kwargs):
        self.fd.read(*args, **kwargs)
        self.fd.flush()
    
    def close(self, *args, **kwargs):
        self.fd.flush()
        self.fd.close(*args, **kwargs)

import sys
import struct
import time
import serial
sys.stdout = FlushDescr(sys.stdout)


DBusGMainLoop(set_as_default=True)

def get_adapter():
    bus = dbus.SystemBus()
    name = bus.get_object('org.bluez',
        '/').DefaultAdapter(dbus_interface='org.bluez.Manager')
    
    return name

class DeviceManager(object):
    UUID = "00001101-0000-1000-8000-00805F9B34FB"

    def __init__(self):
        self.adapter_name = get_adapter()
        self.bus = dbus.SystemBus()
        self.adapter = self.bus.get_object('org.bluez',
            self.adapter_name)
        self.adapter_iface = dbus.Interface(self.adapter, 'org.bluez.Adapter')
        self.devices = []
        self.devices_liveview = []
        
        self.discover = False

    @staticmethod
    def name_test(name):
        return name == "LiveView" or name == "Jerry"

    def initialize(self):
        if self.discover:
            self.discover()
        else:
            self.use_paired()
            
    
    def use_paired(self):
        print "Using paired devices.. "
        devs = self.adapter_iface.ListDevices()
        for dev in devs:
            dev_iface = dbus.Interface(self.bus.get_object('org.bluez',
                dev), 'org.bluez.Device')
            props = dev_iface.GetProperties()

            self.devices.append((str(dev), props))

        self.devices_analysis()

    def discover(self):
        print "Beginning discovery"

        def found_device(*args, **kwargs):
            self.devices.append(args)
        
        self.adapter_iface.connect_to_signal('DeviceFound', found_device)
        self.adapter_iface.StartDiscovery()
        print "Discovery has started..",
        
        def end_discovery():
            self.adapter_iface.StopDiscovery()
            print "done"

            self.devices_analysis()

        timeout_add(15000, end_discovery)

    def devices_analysis(self):
        self.devices_liveview = []
        for i in self.devices:
            props = i[1]
            name = str(props['Name'])

            if DeviceManager.name_test(name):
                self.devices_liveview.append(i)
                if props['Paired'] == 1:
                    print "Starting service discovery '%s'.." % (name,), 

                    dev_iface = dbus.Interface(self.bus.get_object('org.bluez',
                        i[0]), 'org.bluez.Device')
                    try:
                        dev_iface.DiscoverServices('')
                        print "done"
                    except dbus.exceptions.DBusException:
                        print "failed"
                

        print "LiveView devices: ", ",".join(["%s %s" % (str(x[1]['Name']),
            str(x[0])) for x in self.devices_liveview])

    def get_liveview_devices(self):
        return self.devices_liveview

    def connect_to_first_device(self):
        dev = self.devices_liveview[0]
        self.connect_to_device(dev[0])

    def connect_to_device(self, dev):
        dev_obj = self.bus.get_object('org.bluez', dev)
        dev_serial = dbus.Interface(dev_obj,
            dbus_interface='org.bluez.Serial')

        print "Connecting to serial..",
        tty = dev_serial.Connect(DeviceManager.UUID)
        print "done"

        print "Handing over.."
        liveview = LiveViewManager(tty)
        liveview.communicate()
        print "Communication complete"

        dev_serial.Disconnect(tty)

class Packet(object):
    ID_ACK = 44
    STANDBY = 217

    BUTTON_LEFT = 7

    TIME_REQUEST = 38
    TIME_RESPONSE = 39

    TIME_DATE_REQUEST = 15
    TIME_DATE_RESPONSE = 16

    def __init__(self, pId = None, length = None, data = None):
        self.pId = pId
        self.length = length
        self.data = data

        if isinstance(self.pId, str): 
            assert len(self.pId) == 1
            self.pId = chr(self.pId)

        if self.data is not None and len(self.data) == 0:
            self.data = None

    def is_complete(self):
        return self.pId is not None and self.length is not None and \
            self.data is not None

    def is_ack(self):
        return self.pId == self.ID_ACK

    def __repr__(self):
        hexadecimal = ''
        if self.data:
            for x in self.data:
                hexadecimal += '%02X ' % (ord(x),)
        
        if len(hexadecimal) > 0:
            return "<Packet: id %i, length %i, data %s>" % ( self.pId,
                self.length, hexadecimal.strip())
        else:
            return "<Packet: id %i, length %i>" % ( self.pId,
                self.length)


    def __str__(self):
        if self.length > 0:
            return struct.pack(">BBI %is" % self.length, self.pId, 4, self.length, self.data)
        else:
            return struct.pack(">BBI", self.pId, 4, 0)

class LiveViewManager(object):
    def __init__(self, tty):
        self.tty = tty
        self.fd = serial.Serial(self.tty, 4800, timeout=0, rtscts=1)

        self.packet = None
        self.packets = []
    
    def consume(self, data):
        """ Consumes a string of bytes and returns the 
            number of bytes it expects next
        """
        if self.packet is None:
            assert len(data) == 1
            self.packet = Packet()
            self.packet.pId = struct.unpack('>B', data)[0]

            print "packet type: %i" % (self.packet.pId)

            return 5 # byte 0x04 + 4 x bytes for size, in Big-Endian
        else:
            if self.packet.length == None:
                assert len(data) == 5
                four, length = struct.unpack('>BI', data)

                assert four == 4
                self.packet.length = length

                print "packet length: %i" % (self.packet.length)
                return self.packet.length
            else:
                assert len(data) == self.packet.length
                self.packet.data = data
                self.packets.append(self.packet)

                print "packet data:",
                for i in self.packet.data:
                    print "%02X" % ord(i), 
                print ""

                self.packet = None
                return 1

    def send(self, packet):
        print repr(packet),
        self.fd.write(str(packet))
        time.sleep(0.1)

    def send_standby(self):
        print "Sending STANDBY..",
        tmp = Packet(Packet.STANDBY, 0, '')
        self.send(tmp)
        print "sent"

    def communicate(self):
        nextRead = 1
        try:
            self.send_standby()

            while nextRead > 0:
                time.sleep(0.1)

                if self.fd.inWaiting() > 0:
                    tmp = self.fd.read(nextRead)
                
                    if len(tmp) > 0:
                        nextRead = self.consume(tmp)

                        if self.packet is None: # end of prev. packet
                            packet = self.packets[-1]

                            if not packet.is_ack():
                                print "Sending ACK..",

                                tmp = Packet(Packet.ID_ACK, 1, chr(packet.pId))
                                self.send(tmp)
                                
                                print "sent"

                            if packet.pId == Packet.BUTTON_LEFT:
                                self.send_standby()

                            if packet.pId == Packet.TIME_REQUEST:
                                print "Sending TIME_RESPONSE..",
                                
                                localtime = int(time.time()) + 2*3600 
                                data = struct.pack(">LB", localtime,1)

                                tmp = Packet(Packet.TIME_RESPONSE, len(data), data)
                                self.send(tmp)

                                print "sent"
                                print "Localtime is:", localtime

                                self.send_standby()
        finally:
            self.fd.close()
        

if __name__ == "__main__":
    loop = gobject.MainLoop()

    man = DeviceManager()
    man.initialize()
    devs = man.get_liveview_devices()

    if len(devs) > 0:
        man.connect_to_first_device()

    timeout_add(10000, lambda: loop.quit())
    loop.run()
