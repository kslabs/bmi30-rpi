from rpi_hardware_pwm import HardwarePWM
import time

pwm = HardwarePWM(pwm_channel=2, hz=200, chip=2)    # pwm_channel: 3-GPIO_18; 2-GPIO_19; 

pwm.start(50) # full duty cycle
#time.sleep(1)
#pwm.change_duty_cycle(75)
time.sleep(10)
#pwm.change_duty_cycle(10)
#pwm.change_duty_cycle(50)
pwm.change_frequency(9999990)
pwm.stop
pwm.start(0)

