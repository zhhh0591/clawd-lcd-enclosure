#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>
hd44780_I2Cexp lcd;
void setup() {
  int status = lcd.begin(16, 2);
  if (status) hd44780::fatalError(status);
  lcd.setCursor(0, 0);
  lcd.print("TOKEN DISPLAY");
  lcd.setCursor(0, 1);
  lcd.print("HELLO, FUFU!");
}
void loop() {}