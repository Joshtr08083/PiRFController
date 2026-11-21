#include <RCSwitch.h>
#include "driver/rmt.h"
#include <ArduinoJson.h>

#define RX_PIN      16
#define TX_PIN      17
#define PI_RX_PIN 25
#define PI_TX_PIN 26
#define RMT_RX_CH   RMT_CHANNEL_0
#define RMT_TX_CH   RMT_CHANNEL_4
#define MAX_RAW     2048
#define MIN_PULSES  20
#define RAW_REPEATS    1
#define RAW_REPEAT_GAP 50
#define RMT_TICK_US 1

HardwareSerial piSerial(2);
RCSwitch mySwitch = RCSwitch();

void setupRMTReceive() {
  rmt_config_t rmt_rx = {};
  rmt_rx.rmt_mode = RMT_MODE_RX;
  rmt_rx.channel = RMT_RX_CH;
  rmt_rx.gpio_num = (gpio_num_t)RX_PIN;
  rmt_rx.clk_div = 80;
  rmt_rx.mem_block_num = 4;
  rmt_rx.rx_config.filter_en = true;
  rmt_rx.rx_config.filter_ticks_thresh = 100;
  rmt_rx.rx_config.idle_threshold = 65535;
  rmt_config(&rmt_rx);
  rmt_driver_install(RMT_RX_CH, 16384, 0);
}

void setupRMTTransmit() {
  rmt_config_t rmt_tx = {};
  rmt_tx.rmt_mode = RMT_MODE_TX;
  rmt_tx.channel = RMT_TX_CH;
  rmt_tx.gpio_num = (gpio_num_t)TX_PIN;
  rmt_tx.clk_div = 80;
  rmt_tx.mem_block_num = 4;
  rmt_tx.tx_config.loop_en = false;
  rmt_tx.tx_config.carrier_en = false;
  rmt_tx.tx_config.idle_output_en = true;
  rmt_tx.tx_config.idle_level = RMT_IDLE_LEVEL_LOW;
  rmt_config(&rmt_tx);
  rmt_driver_install(RMT_TX_CH, 0, 0);
}

void recordRC() {
  mySwitch.enableReceive(RX_PIN);

  unsigned long deadline = millis() + 5000;
  while (millis() < deadline) {
    if (mySwitch.available()) {
      long val   = mySwitch.getReceivedValue();
      int  bits  = mySwitch.getReceivedBitlength();
      int  proto = mySwitch.getReceivedProtocol();
      int  dly   = mySwitch.getReceivedDelay();
      mySwitch.resetAvailable();

      piSerial.println(String("{\"status\":\"success\",\"type\":\"recRC\",\"protocol\":") + proto + ",\"delay\":" + dly + ",\"bits\":" + bits + ",\"value\":" + val + "}");
      mySwitch.disableReceive();
      return;
    }
  }

  mySwitch.disableReceive();
  piSerial.println("{\"status\":\"failed\",\"error\":\"nothing captured\"}");
}

void recordRAW() {
  setupRMTReceive();
  rmt_rx_start(RMT_RX_CH, true);

  RingbufHandle_t rb;
  rmt_get_ringbuf_handle(RMT_RX_CH, &rb);

  // discard everything for 1 second
  unsigned long drainEnd = millis() + 1000;
  while (millis() < drainEnd) {
    size_t rx_size = 0;
    rmt_item32_t* items =
      (rmt_item32_t*)xRingbufferReceive(rb, &rx_size, 50 / portTICK_PERIOD_MS);
    if (items) vRingbufferReturnItem(rb, items);
  }

  // capture
  rmt_item32_t* captured = nullptr;
  int capturedCount = 0;

  unsigned long deadline = millis() + 5000;

  while (millis() < deadline) {
    size_t rx_size = 0;
    rmt_item32_t* items =
      (rmt_item32_t*)xRingbufferReceive(rb, &rx_size, 50 / portTICK_PERIOD_MS);

    if (items) {
      int pulses = rx_size / sizeof(rmt_item32_t);

      if (pulses >= MIN_PULSES) {
        capturedCount = min(pulses, MAX_RAW);
        captured = (rmt_item32_t*)malloc(capturedCount * sizeof(rmt_item32_t));
        if (captured) memcpy(captured, items, capturedCount * sizeof(rmt_item32_t));
        vRingbufferReturnItem(rb, items);
        break;
      }
      vRingbufferReturnItem(rb, items);
    }
  }

  rmt_rx_stop(RMT_RX_CH);
  rmt_driver_uninstall(RMT_RX_CH);

  if (!captured || capturedCount == 0) {
    piSerial.println("{\"status\":\"failed\", \"error\":\"nothing captured\"}");
    if (captured) free(captured);
    return;
  }

  String code = "";
  for (int i = 0; i < capturedCount; i++) {

      if (code.length()) code += ",";
      int32_t d0 = captured[i].duration0 * RMT_TICK_US;
      code += captured[i].level0 ? d0 : -d0;

      if (captured[i].duration1 > 0) {
          code += ",";
          int32_t d1 = captured[i].duration1 * RMT_TICK_US;
          code += captured[i].level1 ? d1 : -d1;
      }
  }

  piSerial.println(String("{\"status\":\"success\",\"type\":\"recRAW\",\"code\":[") + code + "]}");
  free(captured);
}

void playRC(int protocol, int delayInt, long value, int bits) {
  mySwitch.disableReceive();
  mySwitch.enableTransmit(TX_PIN);

  mySwitch.setProtocol(protocol);
  mySwitch.setPulseLength(delayInt);
  // for (int i = 0; i < 5; i++) {
  //   mySwitch.send(value, bits);
  //   delay(10);
  // }
  mySwitch.send(value, bits);

  mySwitch.disableTransmit();
  piSerial.println("{\"status\":\"success\",\"type\":\"playRC\"}");
}

void playRAW(JsonArray code) {
    int pulseCount = code.size();
    int itemCount  = (pulseCount + 1) / 2;

    rmt_item32_t* items = (rmt_item32_t*)calloc(itemCount, sizeof(rmt_item32_t));
    if (!items) return;

    for (int i = 0; i < pulseCount; i++) {
        int32_t  val = code[i].as<int32_t>();
        uint16_t dur = (uint16_t)abs(val);
        uint8_t  lvl = val > 0 ? 1 : 0;

        if (i % 2 == 0) {
            items[i/2].duration0 = dur;
            items[i/2].level0    = lvl;
        } else {
            items[i/2].duration1 = dur;
            items[i/2].level1    = lvl;
        }
    }

    setupRMTTransmit();
    for (int rep = 0; rep < RAW_REPEATS; rep++) {
        rmt_write_items(RMT_TX_CH, items, itemCount, true);
        if (rep < RAW_REPEATS - 1) delay(RAW_REPEAT_GAP);
    }

    rmt_driver_uninstall(RMT_TX_CH);
    piSerial.println("{\"status\":\"success\",\"type\":\"playRAW\"}");
    free(items);
}

void setup() {
  piSerial.begin(115200, SERIAL_8N1, PI_RX_PIN, PI_TX_PIN);
}

void loop() {
  if (piSerial.available()) {
    String raw = piSerial.readStringUntil('\n');
    raw.trim();

    StaticJsonDocument<4096> doc;
    DeserializationError err = deserializeJson(doc, raw);
    if (err) {
        piSerial.println("{\"status\":\"failed\",\"error\":\"bad json\"}");
        return;
    }

    const String cmd = doc["cmd"];

    if      (cmd == "recordRC") { recordRC(); }
    else if (cmd == "recordRAW") { recordRAW(); }
    else if (cmd == "playRC") { 
      int protocol = doc["protocol"];
      int delayInt = doc["delay"];
      long value = doc["value"];
      int bits = doc["bits"];
      playRC(protocol, delayInt, value, bits);
    }
    else if (cmd == "playRAW") {
      JsonArray code = doc["code"];
      playRAW(code);
    }

  }
}
