# About #

**LivelierView** is an attempt to reverse-engineer the LiveView Bluetooth protocol.

# Current state #

The Python server can currently:
 
 * Identify LiveView devices
 * Set the time of the device
 * Keep it awake
 * Make it vibrate
 * Flash the LED


# Requirements #

The server requires:

 * dbus-python
 * python-gobject (for an event loop that's not currently being used properly - pairing has not yet been implemented)
 * bluez (I'm running 4.77 and that works but I would think any version with
   the same DBus API would work)
 * pyserial (available from PyPi) - I'd like to drop this dependency but I
   haven't bothered to figure out how to do non-blocking reading with Python

The device must already be paired with your computer. To enter pairing mode,
turn off the LiveView device, hold power and keep it pressed while it's
booting.

As a side effect of all the experimentation, I found out that the LiveView
will only ever hold one pairing code in memory - if you pair it with your
computer, you'll have to re-pair it with your phone afterwards.

# Usage #

Either run the script as root, or setup a udev rule to make `/dev/rfcomm0`
world read-/writeable. The latter is left as an exercise for the reader ;)

# TO DO #

* Figure out if the main menu is part of the firmware (judging by the Manager's
resources the icons are coming from the phone) and customize it. 
* Basic navigation/notification

Very far into the future:

* A less sandbox-y plugin system where plugins can spontaneously take over the
  watch.

