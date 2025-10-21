import RPi.GPIO as GPIO
import time

LedPin = 16

GPIO.setmode(GPIO.BCM)
#GPIO.setup(LedPin, GPIO.OUT)

try:    
    GPIO.output(LedPin, True)
    time.sleep(1)
    print('led_on')
    GPIO.output(LedPin, False)
    time.sleep(1)
    print('led_off')
except KeyboardInterrupt:
    print('exit')
    
finally:
    GPIO.cleanup()
    print('end')
        