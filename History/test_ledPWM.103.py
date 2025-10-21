#from gpiod import PWMLED
# Тестовое включение PWM с изменением скважности на обозначенных выводах 


from gpiozero import PWMLED
from time import sleep

led0 = PWMLED(22)		# 22 Вывод
led0.frequency = 100

led1 = PWMLED(13)		# 13 Вывод
led1.frequency = 100

led2 = PWMLED(12)		# 12 Вывод
led2.frequency = 100


try:
    while True:
    #if 1==1:
        for i in range(0,100):
            led0.value = i/100
            led1.value = i/100
            #led2.value = i/100
            sleep(0.01)
        #for i in range(100,0,-1):
        #    led0.value = i/100
        #    led1.value = i/200
        #    led2.value = i/400
            #sleep(0.01)

except KeyboardInterrupt:
    # Закрытие последовательного порта по прерыванию от клавиатуры
    #ser.close()
    #led_line.set_value(1)
    led0.value = 0
    led1.value = 0
    led2.value = 0
    
    print("\nPWM закрыт и светодиод/генератор выключен")