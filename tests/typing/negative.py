"""Each line below must be rejected by both checkers."""
from io import StringIO
import rapidxmltodict as xml

xml.parse('<r/>', froce_list=True)
xml.parse('<r/>', item_depth='two')
xml.parse('<r/>', item_callback=lambda: True)
xml.parse(iter(['<r/>']))
xml.parse(StringIO('<r/>'))
xml.unparse({'r': None}, pretty='yes')
xml.unparse({'r': None}, output=123)
xml.unparse({'r': None}, unknown_option=True)
result: str = xml.unparse({'r': None}, output=StringIO())
