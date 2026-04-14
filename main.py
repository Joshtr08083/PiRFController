import serial
import json
import time
import os
import argparse

def write_remote(remotes, json_data):
    remotes.append(json_data)
    with open("remotes.json", "w") as f:
        json.dump(remotes, f, indent=2)
    print("Successfully wrote new remote")

def remove_remote(remotes, remote_name=None):
    if (remote_name is None):
        print("Available Remotes: ")
        for r in remotes:
            print(f"\t{r['name']}")
        
        remote_name = input("Which remote would you like to use?\n> ")
        
    remotes[:] = [r for r in remotes if r['name'] != remote_name]
    with open("remotes.json", "w") as f:
        json.dump(remotes, f, indent=2)
    print("Successfully removed remote")

def action(ser, command, **kwargs):
    command_data = {
        "cmd": command
    }
    for key, value in kwargs.items():
        command_data[key] = value
        
    json_data = json.dumps(command_data)

    if (command == "recordRC" or command == "recordRAW"): print("START")
    ser.write((json_data + "\n").encode('utf-8'))
    
    timeout = time.time() + 10
    while (time.time() < timeout):
        line = ser.readline()
        if line:
            line = line.decode('utf-8', errors='ignore').strip()
            try:
                output_data = json.loads(line)
            except json.JSONDecodeError:
                print("Invalid JSON Response: ", line)
                return None
            
            return output_data
    print("Serial Timeout; No Response")
    return None

def recordRC(ser, remotes, remote_name):
    input("Have your remote ready, when you see START, press and release the button on the remote\nPress ENTER to continue ")
    output_data = action(ser, "recordRC")
    if output_data is None:
        return

    if (output_data["status"] != "success"):
        print("Action failed: " + output_data["error"])
        return
    
    if remote_name is None:
        remote_name = input("Recording successfull, what would you like to name this remote?\n> ")
    rc_remote = {
        "name": remote_name,
        "type": "rc_remote",
        "protocol": output_data["protocol"],
        "delay": output_data["delay"],
        "bits": output_data["bits"],
        "value": output_data["value"]
    }
    write_remote(remotes, rc_remote)

def recordRAW(ser, remotes, remote_name):
    input("Have your remote ready, \n\n!! PRESS AND HOLD THE BUTTON BEFORE STARTING !!\n\nAfter you see START, wait a good second before releasing\nPress ENTER to continue ")
    
    
    output_data = action(ser, "recordRAW")
    if output_data is None:
        return
    
    if (output_data["status"] != "success"):
        print("Action failed: " + output_data["error"])
        return
    
    if remote_name is None:
        remote_name = input("Recording successfull, what would you like to name this remote?\n> ")
    raw_remote = {
        "name": remote_name,
        "type": "raw_remote",
        "code": output_data["code"],
    }
    write_remote(remotes, raw_remote)

def playRemote(ser, remotes, remote_name=None):
    if (remote_name is None):
        print("Available Remotes: ")
        for r in remotes:
            print(f"\t{r['name']}")
        
        remote_name = input("Which remote would you like to use?\n> ")
    
        
    remote = next((r for r in remotes if r['name'] == remote_name), None)    
    if remote is None:
        print(remote_name + " failed to load")
        return
    
    if (remote['type'] == 'rc_remote'):
        output_data = action(ser, 'playRC', protocol=remote['protocol'], delay=remote['delay'], bits=remote['bits'], value=remote['value'])
    elif (remote['type'] == 'raw_remote'):
        output_data = action(ser, 'playRAW', code=remote['code'])
    
    if output_data is None:
        return
    
    if (output_data["status"] != "success"):
        print("Action failed: " + output_data["error"])
    else:
        print("Played remote successfully")
        

def main(ser):
    if (os.path.exists("remotes.json")):
        with open("remotes.json", "r") as f:
            remotes = json.load(f)
    else:
        remotes = []
            
    parser = argparse.ArgumentParser(description="Record/Play RF Remotes")
    # parser.add_argument("-a", "--action", help="Record/play/remove (Required)")
    parser.add_argument('-a', "--add", action='store_true', help="Flag to add remote")
    parser.add_argument('-r', "--remove", action='store_true', help="Flag to remove remote")
    parser.add_argument('-p', "--play", action='store_true', help="Flag to play remote")
    parser.add_argument("-c", "--rc", action='store_true', help="Flag to specify remote as RC (Only needed for record)")
    parser.add_argument("-w", "--raw", action='store_true', help="Flag to specify remote as RAW (Only needed for record)")
    parser.add_argument("-n", "--name", help="Name of the remote to save/play/remove")
    
    args = parser.parse_args()
    
    if (args.rc):
        remote_type = "RC"
    elif (args.raw):
        remote_type = "RAW"
    else:
        remote_type = None
    
    
    if (args.add):
        if (remote_type == "RC"):
            recordRC(ser, remotes, args.name)
            
        elif (remote_type == "RAW"):
            recordRAW(ser, remotes, args.name)
            
        else:
            print("Missing -c/-w type flag (RC/RAW)")
            
            
    elif (args.remove):
        remove_remote(remotes, args.name)
        
    elif (args.play):
        playRemote(ser, remotes, args.name)
        
    else:
        print("Missing -a/-r/-p flags (record/remove/play)")

if __name__ == "__main__":
    ser = None
    try:
        ser = serial.Serial('/dev/ttyAMA2', 115200, timeout=1)
        main(ser)
    except KeyboardInterrupt:
        pass
    finally:
        if (ser is not None and ser.is_open):
            ser.close()
    