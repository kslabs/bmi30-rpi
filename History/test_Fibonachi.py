import time
start_time = time.time()
fi = (1+5**0.5)*0.5
srt5 = 5**0.5
 
for i in range (1,36):
    print(round(fi**i/srt5),',', sep='', end='')

print("--- %s seconds ---" % (time.time() - start_time))
