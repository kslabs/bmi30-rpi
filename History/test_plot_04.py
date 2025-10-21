import matplotlib.pyplot as plt
import numpy as np

CHUNK_out2 = 100


data_to_sum_p = np.random.rand(CHUNK_out2) 
data_to_sum_n = np.random.rand(CHUNK_out2) 

fig, ax = plt.subplots(figsize=(10, 6))
fig.canvas.manager.set_window_title("?????????????")


x_axis = np.arange(0, CHUNK_out2)  # 
line_p, = ax.plot(x_axis, data_to_sum_p, label='data_to_sum_p', color='blue', linestyle='-')  # 
line_n, = ax.plot(x_axis, data_to_sum_n, label='data_to_sum_n', color='red', linestyle='-')   # 

#
ax.set_ylim(0, 1)  # 
ax.set_xlim(0, CHUNK_out2 - 1)  #
ax.grid(which='major', alpha=0.6, color='green', linestyle='--', linewidth=1.4)
ax.legend(loc='upper right')  # 

# 
while True:
    #
    data_to_sum_p = np.random.rand(CHUNK_out2)  # 
    data_to_sum_n = np.random.rand(CHUNK_out2)

    #
    line_p.set_ydata(data_to_sum_p)  # 
    line_n.set_ydata(data_to_sum_n)  # 

    #
    fig.canvas.draw()
    fig.canvas.flush_events()  #
    plt.pause(0.1)  # 
