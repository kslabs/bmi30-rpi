#from gpiod import PWMLED
from gpiozero import PWMLED
from time import sleep

led = PWMLED(22)
led.frequency = 200

while True:
    for i in range(0,100):
        led.value = i/100
        sleep(0.01)
    for i in range(100,0,-1):
        led.value = i/100
        sleep(0.01)