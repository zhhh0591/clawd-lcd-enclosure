#include <Wire.h>
#include <time.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>
hd44780_I2Cexp lcd;

// The Mac sends one line every few seconds:
//   STATS:<total>,<output>,<replies>,<now>,<last reply>
// Times are seconds since 1970 on the local clock (0 = no reply yet today).
const unsigned long NO_DATA_MS = 60000;   // tokens pages show NO DATA after a minute of silence
const unsigned long PAGE_MS = 4000;       // how long each page stays on screen
const int PAGES = 4;

char buf[96];
int len = 0;

uint64_t total = 0, output = 0;
unsigned long replies = 0;
time_t lastReply = 0;
bool gotData = false;
unsigned long lastData = 0;

time_t clockBase = 0;                     // local time when the last line arrived
unsigned long clockMillis = 0;

int page = 0;
unsigned long pageStart = 0;
time_t drawnSecond = -1;

// 94160868 -> "94,160,868"
void formatTokens(uint64_t n, char *out) {
  char digits[24];
  int d = 0;
  do {
    digits[d++] = '0' + n % 10;
    n /= 10;
  } while (n > 0);
  int o = 0;
  for (int i = d - 1; i >= 0; i--) {
    out[o++] = digits[i];
    if (i > 0 && i % 3 == 0) out[o++] = ',';
  }
  out[o] = '\0';
}

// write both rows, padded to 16 characters so old text gets erased
void show(const char *top, const char *bottom) {
  char row[17];
  snprintf(row, sizeof(row), "%-16s", top);
  lcd.setCursor(0, 0);
  lcd.print(row);
  snprintf(row, sizeof(row), "%-16s", bottom);
  lcd.setCursor(0, 1);
  lcd.print(row);
  Serial.printf("LCD|%s|%s\n", top, bottom);   // mirror to the serial monitor for checking
}

// label on the left, value on the right
void labelValue(char *out, const char *label, const char *value) {
  snprintf(out, 17, "%s%*s", label, 16 - (int)strlen(label), value);
}

time_t now() {
  return clockBase + (millis() - clockMillis) / 1000;
}

void drawPage() {
  char top[17], bottom[17], num[24];
  bool stale = millis() - lastData > NO_DATA_MS;
  time_t t = now();
  struct tm tm;
  gmtime_r(&t, &tm);

  if (page == 0) {
    formatTokens(total, num);
    snprintf(bottom, sizeof(bottom), "%16s", stale ? "NO DATA" : num);
    show("TOKENS TODAY", bottom);
  } else if (page == 1) {
    formatTokens(output, num);
    labelValue(top, "OUTPUT", num);
    snprintf(num, sizeof(num), "%lu", replies);
    labelValue(bottom, "REPLIES", num);
    show(top, stale ? "NO DATA" : bottom);
  } else if (page == 2) {
    strftime(top, sizeof(top), "%a, %b %d %Y", &tm);
    strftime(bottom, sizeof(bottom), "%I:%M:%S %p", &tm);
    show(top, bottom);
  } else {
    if (lastReply == 0) {
      show("LAST REPLY", "none today");
    } else {
      struct tm lt;
      gmtime_r(&lastReply, &lt);
      char clock[9], ago[8];
      strftime(clock, sizeof(clock), "%I:%M %p", &lt);
      long mins = (long)(t - lastReply) / 60;
      if (mins < 1) snprintf(ago, sizeof(ago), "now");
      else if (mins < 60) snprintf(ago, sizeof(ago), "%ldm ago", mins);
      else snprintf(ago, sizeof(ago), "%ldh ago", mins / 60);
      labelValue(bottom, clock, ago);
      show("LAST REPLY", bottom);
    }
  }
  drawnSecond = t;
}

void handleLine(char *line) {
  if (strncmp(line, "STATS:", 6) != 0) return;
  char *p = line + 6;
  uint64_t f[5];
  for (int i = 0; i < 5; i++) {
    char *end;
    f[i] = strtoull(p, &end, 10);
    if (end == p) return;                 // malformed line, keep the old values
    p = (*end == ',') ? end + 1 : end;
  }
  total = f[0];
  output = f[1];
  replies = (unsigned long)f[2];
  clockBase = (time_t)f[3];
  clockMillis = millis();
  lastReply = (time_t)f[4];
  lastData = millis();
  if (!gotData) {
    gotData = true;
    page = 0;
    pageStart = millis();
  }
  drawPage();
}

void setup() {
  Serial.begin(115200);
  int status = lcd.begin(16, 2);
  if (status) hd44780::fatalError(status);
  lcd.setCursor(0, 0);
  lcd.print("TOKEN DISPLAY");
  lcd.setCursor(0, 1);
  lcd.print("HELLO, Honghan!");
}

void loop() {
  // read whatever has arrived without waiting, one line at a time
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[len] = '\0';
      handleLine(buf);
      len = 0;
    } else if (len < (int)sizeof(buf) - 1) {
      buf[len++] = c;
    }
  }

  if (!gotData) return;                   // keep the hello screen until the Mac connects

  if (millis() - pageStart >= PAGE_MS) {
    page = (page + 1) % PAGES;
    pageStart = millis();
    drawPage();
  } else if (page == 2 && now() != drawnSecond) {
    drawPage();                           // tick the clock every second
  }
}
