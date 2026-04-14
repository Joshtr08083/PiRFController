import serial
import threading

ser = serial.Serial('/dev/ttyAMA2', 115200, timeout=1)
stop_event = threading.Event()

def read():
    while not stop_event.is_set():
        line = ser.readline()
        if (line):
            print(line.decode('utf-8', errors='replace').strip())

thread = threading.Thread(target=read)
thread.start()

try:
    while True:
        msg = input()
        ser.write((msg + "\n").encode("utf-8"))
except KeyboardInterrupt:
    pass

stop_event.set()
thread.join()
ser.close()


