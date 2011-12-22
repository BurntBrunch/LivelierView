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

        tty = dev_serial.Connect(DeviceManager.UUID)
        print tty
        dev_serial.Disconnect(self.tty)

class LiveViewManager(object):
    def __init__(self, tty):
        self.tty = tty

    def communicate(self):
        pass

if __name__ == "__main__":
    loop = gobject.MainLoop()

    man = DeviceManager()
    man.initialize()
    devs = man.get_liveview_devices()

    if len(devs) > 0:
        man.connect_to_first_device()

    timeout_add(16000, lambda: loop.quit())
    loop.run()
