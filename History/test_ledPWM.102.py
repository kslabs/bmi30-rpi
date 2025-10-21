#from gpiod import PWMLED
from gpiozero import PWMLED
from time import sleep

led0 = PWMLED(22)		# 22 светодиод
led0.frequency = 200

led1 = PWMLED(13)		# 22 светодиод
led1.frequency = 200

led2 = PWMLED(5)		# 22 светодиод
led2.frequency = 200



while True:
    for i in range(0,100):
        led0.value = i/100
        led1.value = i/200
        led2.value = i/400
        sleep(0.01)
    for i in range(100,0,-1):
        led0.value = i/100
        led1.value = i/200
        led2.value = i/400
        sleep(0.01)
