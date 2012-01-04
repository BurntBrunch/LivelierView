import calendar
import select
import struct
import sys
import termios
import time

import dbus
import serial

from gobject import *
from dbus.mainloop.glib import DBusGMainLoop

class FlushDescr:
    """ A nifty class that makes a buffered stream unbuffered by 
        explicitly flushing it after every IO op """
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


# Make stdout unbuffered - makes `print` instantaneous
sys.stdout = FlushDescr(sys.stdout)

DBusGMainLoop(set_as_default=True)


class DeviceManager(object):
    UUID = "00001101-0000-1000-8000-00805F9B34FB"

    def __init__(self):
        self.bus = dbus.SystemBus()
        self.adapter_name = self.bus.get_object('org.bluez',
            '/').DefaultAdapter(dbus_interface='org.bluez.Manager')

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

        print "TTY created '%s', proceeding.." % (tty,)
        liveview = LiveViewManager(tty)
        liveview.communicate()
        
        print "TTY no longer needed, disconnecting..",
        dev_serial.Disconnect(tty)
        print "done"

class Packet(object):
    ID_ACK = 44

    STANDBY_REQUEST = 7
    STANDBY_RESPONSE = 8

    TIME_REQUEST = 38
    TIME_RESPONSE = 39

    TIME_DATE_REQUEST = 15
    TIME_DATE_RESPONSE = 16

    NAVIGATION_REQUEST = 29
    NAVIGATION_RESPONSE = 30

    LED_REQUEST = 40
    LED_RESPONSE = 41

    VIBRATE_REQUEST = 42
    VIBRATE_RESPONSE = 43

    CLEAR_DISPLAY_REQUEST = 21
    CLEAR_DISPLAY_RESPONSE = 22

    DISPLAY_PROPERTIES_REQUEST = 1
    DISPLAY_PROPERTIES_RESPONSE = 2

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

class StdinManager(object):
    def __init__(self):
        self.key = None

    def read(self):
        key = sys.stdin.read(1)

        self.key = key.lower()

    def quit(self):
        return self.key == 'q'
    
    def vibrate(self):
        return self.key == 'v'

    def led(self):
        return self.key == 'l'

    def clear(self):
        return self.key == 'c'

    def begin(self):
        print "=================================================================="
        print "Starting server, commands are: (q)uit, (v)ibrate, (l)ed, (c)lear"
        print "=================================================================="

        self.__change_tty()

    def end(self):
        self.__revert_tty()
        print "Server stopped."
    
    def __change_tty(self):
        """ This method changes the controlling terminal, so that characters
        can be read before a new line (aka non-canonical mode) and they are not
        echoed as they are typed """
        fd = sys.stdin.fileno()
        self.old_stdin = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)

        # disable echoing
        new[3] = new[3] & ~(termios.ECHO | termios.ICANON)         # lflags

        termios.tcsetattr(fd, termios.TCSADRAIN, new)

    def __revert_tty(self):
        """ This method reverts the changes done by __change_tty() """
        fd = sys.stdin.fileno()
        termios.tcsetattr(fd, termios.TCSADRAIN, self.old_stdin)

class LiveViewManager(object):
    SW_VERSION = "0.0.3"
    
    def __init__(self, tty):
        self._24hour_clock = False
        
        self.vibrateOnTime = 50
        self.vibrateDelayTime = 100

        self.ledOnTime = 250
        self.ledDelayTime = 100
        self.ledColor = (31, 63, 31)

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

            #print "packet type: %i" % (self.packet.pId)

            return 5 # byte 0x04 + 4 x bytes for size, in Big-Endian
        else:
            if self.packet.length == None:
                assert len(data) == 5
                four, length = struct.unpack('>BI', data)

                assert four == 4
                self.packet.length = length

                #print "packet length: %i" % (self.packet.length)
                return self.packet.length
            else:
                assert len(data) == self.packet.length
                self.packet.data = data
                self.packets.append(self.packet)

                """print "packet data:",
                for i in self.packet.data:
                    print "%02X" % i, 
                print "" """

                print "Received packet: ", repr(self.packet)

                self.packet = None
                return 1

    def send(self, packet):
        print repr(packet),
        self.fd.write(str(packet))
        time.sleep(0.1)

    def send_standby(self):
        print "Sending STANDBY..",
        tmp = Packet(Packet.STANDBY_RESPONSE, 0, '')
        self.send(tmp)
        print "sent"

    def debug_navigation(self, packet):
        data = packet.data

        if data[0] == 0x0 and data[1] == 0x3:
            print "Navitation packet:",

            up     = (1,2,3)
            down   = (4,5,6)
            left   = (7,8,9)
            right  = (10,11,12)
            select = (13,14,15)
            open_  = (32,)
            ignore = tuple(range(16,31+1))
            
            dirc = data[2]
            if dirc in up:
                print "up",
            elif dirc in down:
                print "down",
            elif dirc in left:
                print "left",
            elif dirc in right:
                print "right",
            elif dirc in select:
                print "select",
            elif dirc in open_:
                print "open",
            elif dirc in ignore:
                print "ignore",

            print "pos x: %i, pos y: %i"% (data[3], data[4])

        else:
            print "Not a navigation packet!"

    def debug_dpr(self,packet):
        data = packet.data

        data = struct.unpack(">10B B %is" % (len(data) - 11) , data)
        (width, height, sbWidth, sbHeight, viewWidth, viewHeight, aWidth,
         aHeight, textChunkSize, idleTimer, stopbyte, version) = data

        print "\nParsing response - (a* = announce*, sb* = status bar*)"
        print "Width Height sbWidth sbHeight viewWidth viewHeight"
        print "%5i %6i %7i %8i %9i %10i" % ( width, height, sbWidth, sbHeight,
                                            viewWidth, viewHeight)
        
        print "aWidth aHeight textChunk idleTimer"
        print "%6i %7i %9i %9i" % (aWidth, aHeight, textChunkSize, idleTimer)

        print "Software version: '%s'\n" % (version,)
        

    def communicate(self):
        nextRead = 1
        stdinman = StdinManager()

        try:
            stdinman.begin()
            self.send_standby()

            print "Sending DPR..",
            data = LiveViewManager.SW_VERSION
            data = struct.pack('>%is' % (len(data) + 1), data)
            tmp = Packet(Packet.DISPLAY_PROPERTIES_REQUEST, len(data), data)
            self.send(tmp)
            print "sent"

            while nextRead > 0:
                (seqin, seqout, seqex) = select.select([self.fd, sys.stdin],
                                                       [], [])
                if sys.stdin in seqin:
                    stdinman.read()

                    if stdinman.quit():
                        break

                    if stdinman.vibrate():
                        print "Vibrating for %i ms, delay %i ms.." % (
                            self.vibrateOnTime, self.vibrateDelayTime),
                        
                        # pack the times as unsigned shorts
                        data = struct.pack(">HH", self.vibrateDelayTime, self.vibrateOnTime)

                        tmp = Packet(Packet.VIBRATE_REQUEST, len(data), data)
                        self.send(tmp)

                        print "sent"

                    if stdinman.led():
                        print "LED on for %i ms, delay %i ms, R%i G%i B%i.." % (
                            self.ledOnTime, self.ledDelayTime,
                            self.ledColor[0], self.ledColor[1],
                            self.ledColor[2]),
                        
                        red, green, blue = self.ledColor

                        # pack the colors as RGB 565
                        color = (red & 31) << 11 |\
                                (green & 63) << 5 |\
                                (blue & 31)

                        data = struct.pack(">HHH", color, self.ledDelayTime,
                                           self.ledOnTime)

                        tmp = Packet(Packet.LED_REQUEST, len(data), data)
                        self.send(tmp)

                        print "sent"

                    if stdinman.clear():
                        print "Clearing display..",
                        
                        tmp = Packet(Packet.CLEAR_DISPLAY_REQUEST, 0, '')
                        self.send(tmp)
                        
                        print "sent"

                if self.fd in seqin and self.fd.inWaiting() > 0:
                    assert self.fd.inWaiting() >= nextRead
                    tmp = self.fd.read(nextRead)
                
                    if len(tmp) > 0:
                        nextRead = self.consume(tmp)

                        if self.packet is None: # end of prev. packet
                            packet = self.packets[-1] # last packet

                            if not packet.is_ack():
                                print "Sending ACK..",

                                tmp = Packet(Packet.ID_ACK, 1, chr(packet.pId))
                                self.send(tmp)
                                
                                print "sent"

                            packet_nops = {
                                Packet.VIBRATE_RESPONSE: "VIBRATE_RESPONSE",
                                Packet.LED_RESPONSE: "LED_RESPONSE",
                                Packet.CLEAR_DISPLAY_RESPONSE: "CLEAR_DISPLAY_RESPONSE",
                            }

                            if packet.pId in packet_nops:
                                print "Got %s" % (packet_nops[packet.pId],)

                            if packet.pId == Packet.DISPLAY_PROPERTIES_RESPONSE:
                                print "Got DISPLAY_PROPERTIES_RESPONSE"
                                self.debug_dpr(packet)
                                self.send_standby()

                            if packet.pId == Packet.STANDBY_REQUEST:
                                if packet.data == [0x2]:
                                    print "Standby mode: awake"
                                elif packet.data == [0x1]:
                                    print "Standby mode: in clock"
                                elif packet.data == [0x0]:
                                    print "Standby mode: sleeping"

                                self.send_standby()

                            if packet.pId == Packet.TIME_REQUEST:
                                print "Sending TIME_RESPONSE..",
                                
                                # time in seconds since the Epoch, in local
                                # time zone, with DST taken into account
                                localtime = calendar.timegm(time.localtime())
                                data = struct.pack(">LB", localtime,
                                    self._24hour_clock)

                                tmp = Packet(Packet.TIME_RESPONSE, len(data), data)
                                self.send(tmp)
                                print "sent"

                                self.send_standby()
                            
                            if packet.pId == Packet.NAVIGATION_REQUEST:
                                self.debug_navigation(packet)

                                print "Sending NAVIGATION_RESPONSE..",

                                tmp = Packet(Packet.NAVIGATION_RESPONSE, 1,
                                             chr(0))
                                self.send(tmp)
                                print "sent"

        except IOError as e:
            print "Communication terminated:", e

        finally:
            self.fd.close()

            stdinman.end()
        

if __name__ == "__main__":
    man = DeviceManager()
    man.initialize()
    devs = man.get_liveview_devices()

    if len(devs) > 0:
        man.connect_to_first_device()
