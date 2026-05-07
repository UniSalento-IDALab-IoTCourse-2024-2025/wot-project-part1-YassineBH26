from gpiozero import DigitalInputDevice
import time

tilt = DigitalInputDevice(17, pull_up=False)

print("KY-017 tilt sensor test")
print("Tilt the sensor to see changes")
print("Press CTRL+C to stop")

try:
    while True:
        if tilt.value:
            print("Tilt detected!")
        else:
            print("Normal position")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nExiting...")
