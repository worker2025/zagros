"""Tiny starter programs for beginners (`examples`, `example <name>`, `new <file>`)."""
from __future__ import annotations

# name -> (title, source, sample stdin lines used by the tests)
EXAMPLES: dict[str, tuple[str, str, list[str]]] = {
    "hello": ("سلام دنیا", '''\
# اولین برنامه
print("سلام دنیا!")
name = input("نام شما چیست؟ ")
print("خوشحالم که دیدمت،", name)
''', ["علی"]),
    "calc": ("ماشین‌حساب ساده", '''\
# ماشین‌حساب ساده
a = float(input("عدد اول: "))
b = float(input("عدد دوم: "))
print("جمع:", a + b)
print("تفریق:", a - b)
print("ضرب:", a * b)
if b != 0:
    print("تقسیم:", a / b)
else:
    print("تقسیم بر صفر ممکن نیست!")
''', ["6.5", "2"]),
    "guess": ("بازی حدس عدد", '''\
# بازی حدس عدد
import random

secret = random.randint(1, 10)
tries = 0
while True:
    guess = int(input("عددی بین 1 تا 10 حدس بزنید: "))
    tries += 1
    if guess == secret:
        print(f"آفرین! بعد از {tries} حدس پیدا کردید.")
        break
    elif guess < secret:
        print("بزرگ‌تر است.")
    else:
        print("کوچک‌تر است.")
''', [str(i) for i in range(1, 11)]),
    "table": ("جدول ضرب", '''\
# جدول ضرب
n = int(input("جدول ضرب چه عددی؟ "))
for i in range(1, 11):
    print(f"{n} × {i} = {n * i}")
''', ["7"]),
    "temp": ("تبدیل دما", '''\
# تبدیل سلسیوس به فارنهایت
c = float(input("دما به سلسیوس: "))
f = round(c * 9 / 5 + 32, 1)
print(f"{c} درجه‌ی سلسیوس = {f} درجه‌ی فارنهایت")
''', ["36.6"]),
    "clock": ("ساعت (برای حالت نمایش بزرگ)", '''\
# ساعت فعلی
import datetime

print(datetime.datetime.now().strftime("%H:%M:%S"))
''', []),
}

TEMPLATE = '''\
# برنامه‌ی من
name = input("نام شما چیست؟ ")
print("سلام", name)
'''
