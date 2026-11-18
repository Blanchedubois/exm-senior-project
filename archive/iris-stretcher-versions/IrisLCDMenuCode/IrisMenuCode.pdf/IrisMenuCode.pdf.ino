#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>

// ---------- Encoder direction ----------
#define ENC_INVERT_DIR 0  // set to 1 to flip rotation direction

// ================= USER CONFIG =================
#define USE_INTERNAL_PULLDOWN  1   // 1: use INPUT_PULLDOWN; 0: use INPUT (for external pulldowns)
//#define CUSTOM_I2C_PINS          // uncomment if you use non-default I2C pins
//#define I2C_SDA_PIN  3
//#define I2C_SCL_PIN  4
// =================================================

// ---------- About/FW metadata ----------
#define FW_NAME     "Iris Stretcher"
#define FW_VERSION  "v1.0.0"
#define FW_CREATOR  "Tejasvin Shrikanth"
#define FW_LABLINE1 "Kisely Lab"
#define FW_LABLINE2 "CWRU"
#define FW_BUILDDATE __DATE__
#define FW_BUILDTIME __TIME__

// --------- Pins (buttons pressed==HIGH with pulldowns) ----------
const uint8_t BTN_MENU   = A0;   // change if A0..A5 map to GPIO34-39 on your board
const uint8_t BTN_DOWN   = A1;
const uint8_t BTN_ACCEPT = A2;
const uint8_t ENC_A      = A5;   // encoder A (keep INPUT_PULLUP for quadrature)
const uint8_t ENC_B      = A4;   // encoder B
const uint8_t ENC_SW     = A3;   // encoder push (pressed==HIGH with pulldown)

// --------- LCD ----------
hd44780_I2Cexp lcd;
const int LCD_COLS = 16, LCD_ROWS = 2;

// --------- Menu ----------
enum class MenuItem : uint8_t { XsetZero, Xzero, Xcalibrate, Xspeed, Xgoto, Xhelp, Xabout, COUNT };
const char* const MENU_LABELS[] = {"XsetZero","Xzero","Xcalibrate","Xspeed","Xgoto","Xhelp","Xabout"};
uint8_t menuIndex = 0;

// Ranges
const float XSPEED_MIN = 0.1f,  XSPEED_MAX = 5.0f,   XSPEED_STEP = 0.1f;
const float XGOTO_MIN  = 1.001f, XGOTO_MAX  = 4.200f, XGOTO_STEP  = 0.001f;
float xSpeedValue = 1.0f;
float xGotoValue  = 1.500f;

// ---------- Debounced buttons (activeHigh = pressed==HIGH) ----------
struct DebouncedButton {
  uint8_t pin; bool activeLevel = true; bool s, r; unsigned long t=0; const unsigned long db=25;
  void begin(uint8_t mode /*INPUT/INPUT_PULLUP/INPUT_PULLDOWN*/, bool activeHigh){
    pinMode(pin, mode); activeLevel = activeHigh; s = r = digitalRead(pin); t = millis();
  }
  uint8_t edge(){ bool x=digitalRead(pin); unsigned long now=millis();
    if(x!=r){ r=x; t=now; }
    if(now - t >= db && r != s){
      bool wasPressed = (s == activeLevel);
      s = r;
      bool nowPressed = (s == activeLevel);
      if (wasPressed && !nowPressed) return 1; // released
      if (!wasPressed && nowPressed) return 2; // pressed
    }
    return 0;
  }
  bool fell(){ return edge()==2; }
  bool isPressed() const { return s==activeLevel; }
};

// ---------- Encoder (detent-latched) ----------
struct Encoder {
  uint8_t a,b;
  uint8_t last=0;
  int8_t accum=0;   // accumulate transitions until reaching a detent

  void begin(uint8_t A,uint8_t B){
    a=A; b=B;
    pinMode(a, INPUT_PULLUP);
    pinMode(b, INPUT_PULLUP);
    last = (digitalRead(a)<<1) | digitalRead(b);
  }

  // Returns: -1, 0, +1 (at most one step per *detent*)
  int8_t step(){
    uint8_t s = (digitalRead(a)<<1) | digitalRead(b);
    static const int8_t quad[16] = {
      0,-1,+1, 0,
      +1, 0, 0,-1,
      -1, 0, 0,+1,
       0,+1,-1, 0
    };
    int8_t d = quad[(last<<2)|s];
    last = s;

    if (d) accum += d;  // collect sub-steps from bounce/transition

    // Commit when resting on a detent state (00 or 11) and we traversed a full cycle
    if ((s==0 || s==3) && (accum >= 4 || accum <= -4)) {
      int8_t out = (accum > 0) ? +1 : -1;
      accum = 0;
      return out;
    }
    return 0;
  }
} enc;

// ---------- UI ----------
enum class UiState : uint8_t { MENU, RUNNING, EDIT_XSPEED, EDIT_XGOTO };
UiState ui = UiState::MENU;
unsigned long statusUntil = 0;

// ---------- Stubs to link (override with your real ones) ----------
__attribute__((weak)) void XsetZero(){ }
__attribute__((weak)) void Xzero(){ }
__attribute__((weak)) void Xcalibrate(){ }
__attribute__((weak)) void Xspeed(float){ }
__attribute__((weak)) void Xgoto(float){ }

// ---------- Utils ----------
template<typename T> T clamp(T v,T lo,T hi){ if(v<lo) return lo; if(v>hi) return hi; return v; }
float roundToStep(float x,float st){ return (float)((long)lround(x/st))*st; }
void printFloatFixed(float v, uint8_t places){
  long scale=1; for(uint8_t i=0;i<places;i++) scale*=10;
  long s = lround(v*scale); long ip = s/scale; long fp = labs(s%scale);
  lcd.print(ip); lcd.print('.');
  long div = scale/10;
  for(uint8_t i=1;i<places;i++){ if(fp<div) lcd.print('0'); div/=10; }
  lcd.print(fp);
}

// ---------- Drawing ----------
void drawMenu(){
  lcd.clear();
  lcd.setCursor(0,0); lcd.write(byte(0x7E)); lcd.print(MENU_LABELS[menuIndex]);
  lcd.setCursor(0,1); lcd.print(' ');
  uint8_t next=(menuIndex+1)%(uint8_t)MenuItem::COUNT;
  lcd.print(MENU_LABELS[next]);
}
void drawStatus(const char* msg){
  lcd.clear();
  lcd.setCursor(0,0); lcd.print(msg);
  lcd.setCursor(0,1); lcd.print("Running...");
}
void drawEditXspeed(){ lcd.clear(); lcd.setCursor(0,0); lcd.print("Xspeed:");
  lcd.setCursor(0,1); printFloatFixed(xSpeedValue,1); lcd.print("  [SW]"); }
void drawEditXgoto(){  lcd.clear(); lcd.setCursor(0,0); lcd.print("Xgoto:");
  lcd.setCursor(0,1); printFloatFixed(xGotoValue,3); lcd.print("  [SW]"); }
void drawHelp(){  
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Commands:");
  lcd.setCursor(0,1); lcd.print("________");
  delay(2000);

  lcd.clear();
  lcd.setCursor(0,0); lcd.print("1.Xgoto <value>");
  lcd.setCursor(0,1); lcd.print("  move to set Ex");
  delay(2000);

  lcd.clear();
  lcd.setCursor(0,0); lcd.print("2.Xzero");
  lcd.setCursor(0,1); lcd.print("  moves to 1x");
  delay(2000);

  lcd.clear();
  lcd.setCursor(0,0); lcd.print("3.XsetZero");
  lcd.setCursor(0,1); lcd.print("  current Ex=1x");
  delay(2000);

  lcd.clear();
  lcd.setCursor(0,0); lcd.print("4.Xcalibrate");
  lcd.setCursor(0,1); lcd.print("  calibrates 1x");
  delay(2000);

  lcd.clear();
  lcd.setCursor(0,0); lcd.print("5.Xspeed <v>");
  lcd.setCursor(0,1); lcd.print("  set speed cm/s");
  delay(2000);

  lcd.clear();
  lcd.setCursor(0,0); lcd.print("6.Xhelp");
  lcd.setCursor(0,1); lcd.print("  this message");
  delay(2000);
}

// --------- About screens ---------
void drawAbout(){
  // Page 1: name + version
  lcd.clear();
  lcd.setCursor(0,0); lcd.print(FW_NAME);
  lcd.setCursor(0,1); lcd.print("FW "); lcd.print(FW_VERSION);
  delay(2200);

  // Page 2: build date/time
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Build:");
  lcd.setCursor(0,1); lcd.print(FW_BUILDDATE);
  delay(1500);

  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Build time:");
  lcd.setCursor(0,1); lcd.print(FW_BUILDTIME);
  delay(1500);

  // Page 3: creator
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Creator:");
  lcd.setCursor(0,1); lcd.print(FW_CREATOR);
  delay(2200);

  // Page 4: lab/affiliation
  lcd.clear();
  lcd.setCursor(0,0); lcd.print(FW_LABLINE1);
  lcd.setCursor(0,1); lcd.print(FW_LABLINE2);
  delay(1800);

  // Page 5: encoder direction
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Encoder dir:");
  lcd.setCursor(0,1);
#if ENC_INVERT_DIR
  lcd.print("inverted");
#else
  lcd.print("normal");
#endif
  delay(1500);

  // Page 6: button wiring mode
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Buttons:");
  lcd.setCursor(0,1);
#if USE_INTERNAL_PULLDOWN
  lcd.print("INT pulldown");
#else
  lcd.print("EXT pulldown");
#endif
  delay(1500);
}

// ---------- Actions ----------
void runAction(MenuItem it){
  switch(it){
    case MenuItem::XsetZero:   drawStatus("XsetZero");   XsetZero();   statusUntil=millis()+1200; ui=UiState::RUNNING; break;
    case MenuItem::Xzero:      drawStatus("Xzero");      Xzero();      statusUntil=millis()+1200; ui=UiState::RUNNING; break;
    case MenuItem::Xcalibrate: drawStatus("Xcalibrate"); Xcalibrate(); statusUntil=millis()+1200; ui=UiState::RUNNING; break;

    case MenuItem::Xspeed:
      ui=UiState::EDIT_XSPEED; drawEditXspeed(); break;

    case MenuItem::Xgoto:
      ui=UiState::EDIT_XGOTO;  drawEditXgoto();  break;

    case MenuItem::Xhelp:
      drawHelp(); statusUntil=millis()+5000; ui=UiState::RUNNING; break;

    case MenuItem::Xabout:
      drawAbout(); statusUntil=millis()+4000; ui=UiState::RUNNING; break;
  }
}

// ---------- Buttons ----------
DebouncedButton btnMenu  { BTN_MENU };
DebouncedButton btnDown  { BTN_DOWN };
DebouncedButton btnAccept{ BTN_ACCEPT };
DebouncedButton btnEncSW { ENC_SW };

// ---------- Setup ----------
void setup(){
  // I2C
#ifdef CUSTOM_I2C_PINS
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
#else
  Wire.begin();                // default pins for your board
#endif
  lcd.begin(LCD_COLS, LCD_ROWS);
  lcd.backlight();

  // Buttons: choose mode based on internal vs external pulldown
#if USE_INTERNAL_PULLDOWN
  btnMenu.begin(  INPUT_PULLDOWN, /*activeHigh=*/true);
  btnDown.begin(  INPUT_PULLDOWN, /*activeHigh=*/true);
  btnAccept.begin(INPUT_PULLDOWN, /*activeHigh=*/true);
  btnEncSW.begin( INPUT_PULLDOWN, /*activeHigh=*/true);
#else
  btnMenu.begin(  INPUT, /*activeHigh=*/true);   // expect external 10k pulldown to GND
  btnDown.begin(  INPUT, /*activeHigh=*/true);
  btnAccept.begin(INPUT, /*activeHigh=*/true);
  btnEncSW.begin( INPUT, /*activeHigh=*/true);
#endif

  // Encoder
  enc.begin(ENC_A, ENC_B);

  // Boot diagnostic: hold MENU to see raw states
  if (btnMenu.isPressed()){
    lcd.clear();
    lcd.setCursor(0,0); lcd.print("Diag:BTN raw");
    for (int i=0;i<200;i++){ // ~2s
      lcd.setCursor(0,1);
      lcd.print("M:"); lcd.print(digitalRead(BTN_MENU));
      lcd.print(" D:"); lcd.print(digitalRead(BTN_DOWN));
      lcd.print(" A:"); lcd.print(digitalRead(BTN_ACCEPT));
      lcd.print(" SW:"); lcd.print(digitalRead(ENC_SW));
      delay(10);
    }
  }

  lcd.clear(); lcd.setCursor(0,0); lcd.print(FW_NAME); lcd.setCursor(0,1); lcd.print(FW_LABLINE1);
  delay(1000);
  drawMenu();
}

// ---------- Loop ----------
void loop(){
  int8_t ed = enc.step();
  #if ENC_INVERT_DIR
    ed = -ed;
  #endif

  switch(ui){
    case UiState::MENU: {
      if (ed == +1) {
        menuIndex = (menuIndex + 1) % (uint8_t)MenuItem::COUNT;      // wrap-around
        drawMenu();
      } else if (ed == -1) {
        menuIndex = (menuIndex + (uint8_t)MenuItem::COUNT - 1) % (uint8_t)MenuItem::COUNT;
        drawMenu();
      }
      if (btnDown.fell())   { menuIndex=(menuIndex+1)%(uint8_t)MenuItem::COUNT; drawMenu(); }
      if (btnAccept.fell()) { runAction(static_cast<MenuItem>(menuIndex)); }
      if (btnMenu.fell())   { lcd.noBacklight(); delay(60); lcd.backlight(); }
    } break;

    case UiState::RUNNING:
      if (millis() >= statusUntil || btnMenu.fell()){ ui=UiState::MENU; drawMenu(); }
      break;

    case UiState::EDIT_XSPEED: {
      if (ed == +1) {
        xSpeedValue = clamp(roundToStep(xSpeedValue + XSPEED_STEP, XSPEED_STEP), XSPEED_MIN, XSPEED_MAX);
        drawEditXspeed();
      } else if (ed == -1) {
        xSpeedValue = clamp(roundToStep(xSpeedValue - XSPEED_STEP, XSPEED_STEP), XSPEED_MIN, XSPEED_MAX);
        drawEditXspeed();
      }
      if (btnEncSW.fell() || btnAccept.fell()){
        drawStatus("Xspeed set"); Xspeed(xSpeedValue);
        statusUntil=millis()+1200; ui=UiState::RUNNING;
      }
      if (btnMenu.fell()){ ui=UiState::MENU; drawMenu(); }
    } break;

    case UiState::EDIT_XGOTO: {
      if (ed == +1) {
        xGotoValue = clamp(roundToStep(xGotoValue + XGOTO_STEP, XGOTO_STEP), XGOTO_MIN, XGOTO_MAX);
        drawEditXgoto();
      } else if (ed == -1) {
        xGotoValue = clamp(roundToStep(xGotoValue - XGOTO_STEP, XGOTO_STEP), XGOTO_MIN, XGOTO_MAX);
        drawEditXgoto();
      }
      if (btnEncSW.fell() || btnAccept.fell()){
        drawStatus("Xgoto set"); Xgoto(xGotoValue);
        statusUntil=millis()+1200; ui=UiState::RUNNING;
      }
      if (btnMenu.fell()){ ui=UiState::MENU; drawMenu(); }
    } break;
  }
}