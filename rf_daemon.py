import serial
import json
import time
import os
import paho.mqtt.client as mqtt

SERIAL = {
    "PORT": "/dev/ttyAMA2",
    "BAUD": 115200,
    "TIMEOUT": 1
}

MQTT = {
    "HOST": "localhost",
    "PORT": 1883,
    "USER": None,
    "PASSWORD": None,
    "TOPIC_CMD": "rf_rem/command",
    "TOPIC_STATUS": "rf_rem/status",
    "TOPIC_DISCOVERY": "homeassistant/button/rf_rem/{name}/config"
}

def load_remotes():
    if (os.path.exists("remotes.json")):
        with open("remotes.json", "r") as f:
            return json.load(f)
    return []

def write_remote(remotes, json_data):
    remotes.append(json_data)
    with open("remotes.json", "w") as f:
        json.dump(remotes, f, indent=2)
    print("Successfully wrote new remote")

def remove_remote(remotes, remote_name):
    try:
        before = len(remotes)
        remotes[:] = [r for r in remotes if r['name'] != remote_name]
        if len(remotes) == before:
            return False, "Remote not found"
        
        with open("remotes.json", "w") as f:
            json.dump(remotes, f, indent=2)
        
        return True, None
    
    except Exception as e:
        return False, f"Unexpected error: {e}"
    
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

def record_RC(ser, remotes, remote_name):
    try:
        output_data = action(ser, "recordRC")
        if output_data is None:
            return False, "No output. ESP32 likely timed-out"

        if (output_data["status"] != "success"):
            print("Action failed: " + output_data["error"])
            return False, output_data["error"]

        rc_remote = {
            "name": remote_name,
            "type": "rc_remote",
            "protocol": output_data["protocol"],
            "delay": output_data["delay"],
            "bits": output_data["bits"],
            "value": output_data["value"]
        }
        write_remote(remotes, rc_remote)
        
        return True, rc_remote
    
    except Exception as e:
        return False, f"Unexpected error: {e}"

def record_RAW(ser, remotes, remote_name):
    try:
        output_data = action(ser, "recordRAW")
        if output_data is None:
            return False, "No output. ESP32 likely timed-out"
        
        if (output_data["status"] != "success"):
            print("Action failed: " + output_data["error"])
            return False, f"ESP32 Error: {output_data["error"]}"

        raw_remote = {
            "name": remote_name,
            "type": "raw_remote",
            "code": output_data["code"],
        }
        write_remote(remotes, raw_remote)
        return True, raw_remote
        
    except Exception as e:
        return False, f"Unexpected error: {e}"

def play_remote(ser, remotes, remote_name=None):    
    try:
        remote = next((r for r in remotes if r['name'] == remote_name), None)    
        if remote is None:
            return False, f"{remote_name} does not exist"
        
        if (remote['type'] == 'rc_remote'):
            output_data = action(ser, 'playRC', protocol=remote['protocol'], delay=remote['delay'], bits=remote['bits'], value=remote['value'])
        elif (remote['type'] == 'raw_remote'):
            output_data = action(ser, 'playRAW', code=remote['code'])
        
        if output_data is None:
            return False, "No output. ESP32 likely timed-out"
        
        if (output_data["status"] != "success"):
            print("Action failed: " + output_data["error"])
            return False, f"ESP32 Error: {output_data["error"]}"
        else:
            print("Played remote successfully")
            return True, None
            
    except Exception as e:
        return False, f"Unexpected error: {e}"

def publish(client, remote):
    name = remote["name"]
    topic = MQTT["TOPIC_DISCOVERY"].format(name=name.replace(" ", "_"))
    
    config = {
        "name": name,
        "unique_id": f"rf_remote_{name.replace(' ', '_')}",
        "command_topic": MQTT["TOPIC_CMD"],
        "payload_press": json.dumps({"action": "play", "name": name}),
        "device": {
            "identifiers": ["rf_remote_pi"],
            "name": "RF Remote",
            "model": "Unknown",
            "manufacturer": "None",
        },
    }
    
    client.publish(topic, json.dumps(config), retain=True)
    print("Published remote")
    
def publish_all(client, remotes):
    for remote in remotes:
        publish(client, remote)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connected MQTT on {MQTT["HOST"]}:{MQTT["PORT"]}")
        client.subscribe(MQTT["TOPIC_CMD"])
        print(f"Subscribed to {MQTT["TOPIC_CMD"]}")
        publish_all(client, userdata["remotes"])
    else:
        print(f"MQTT connection failed ({reason_code})")

def on_message(client, userdata, msg):
    ser     = userdata["ser"]
    remotes = userdata["remotes"]
 
    try:
        data = json.loads(msg.payload.decode())
    
        action_name  = data.get("action")
        remote_name  = data.get("name")
        remote_type  = data.get("remote_type")
    
        print(f"Command received: action={action_name} name={remote_name}")

        if action_name == "play":
            success, result = play_remote(ser, remotes, remote_name)
            client.publish(MQTT["TOPIC_STATUS"], json.dumps({
                "action": "play",
                "name":   remote_name,
                "status": "success" if success else "error",
                "error":  None if success else result,
            }))
    
        elif action_name == "record":
            if not remote_name:
                client.publish(MQTT["TOPIC_STATUS"], json.dumps({"status": "error", "error": "No name provided"}))
                return
    
            client.publish(MQTT["TOPIC_STATUS"], json.dumps({"action": "record", "status": "ready", "name": remote_name}))
    
            if remote_type == "RC":
                success, result = record_RC(ser, remotes, remote_name)
            elif remote_type == "RAW":
                success, result = record_RAW(ser, remotes, remote_name)
            else:
                client.publish(MQTT["TOPIC_STATUS"], json.dumps({"status": "error", "error": "Invalid remote_type (use RC or RAW)"}))
                return
    
            if success:
                publish(client, result)
                client.publish(MQTT["TOPIC_STATUS"], json.dumps({"action": "record", "status": "success", "name": remote_name}))
            else:
                client.publish(MQTT["TOPIC_STATUS"], json.dumps({"action": "record", "status": "error", "error": result}))
    
        elif action_name == "remove":
            success, result = remove_remote(remotes, remote_name)
            client.publish(MQTT["TOPIC_STATUS"], json.dumps({
                "action": "remove",
                "name":   remote_name,
                "status": "success" if success else "error",
                "error":  None if success else result,
            }))

        elif action_name == "list":
            names = [r["name"] for r in remotes]
            client.publish(MQTT["TOPIC_STATUS"], json.dumps({"action": "list", "remotes": names}))
    
        else:
            print(f"Unknown MQTT action: {action_name}")
            
    except json.JSONDecodeError:
        print(f"Bad payload: {msg.payload}")
    except Exception as e:
        print(f"Unexpected error: {e}")
        client.publish(MQTT["TOPIC_STATUS"], json.dumps({"status": "error", "error": str(e)}))

def main():
    remotes = load_remotes()
    ser = serial.Serial(SERIAL["PORT"], SERIAL["BAUD"], timeout=SERIAL["TIMEOUT"])
    print("Opened serial on " + SERIAL["PORT"])
    
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata={"ser": ser, "remotes": remotes})
    client.on_connect = on_connect
    client.on_message = on_message
    
    if (MQTT["USER"]):
        client.username_pw_set(MQTT["USER"], MQTT["PASSWORD"])
    
    client.connect(MQTT["HOST"], MQTT["PORT"], keepalive=60)
    
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        client.disconnect()
        
if __name__ == "__main__":
    main()