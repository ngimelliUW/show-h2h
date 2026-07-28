"""Check the perspective flip is a true mirror, not just non-crashing."""
from streamlit.testing.v1 import AppTest
from show_h2h import config

seen = {}
for viewer in (config.MY_USERNAME, config.FRIEND_USERNAME):
    at = AppTest.from_file("app/dashboard.py", default_timeout=180)
    at.run()
    at.radio[0].set_value(viewer).run()
    at.radio[1].set_value("Rivalry").run()
    m = {x.label: x.value for x in at.metric}
    seen[viewer] = m
    print(f"{viewer}: {m}")

a, b = seen[config.MY_USERNAME], seen[config.FRIEND_USERNAME]
aw, al = a["Record"].split("–")
bw, bl = b["Record"].split("–")
print("\nrecord is mirrored:", (aw, al) == (bl, bw), f"({a['Record']} vs {b['Record']})")
print("run diff is negated:", a["Run diff"].lstrip("+") == b["Run diff"].lstrip("-"),
      f"({a['Run diff']} vs {b['Run diff']})")
print("games identical:", a["Games"] == b["Games"])
