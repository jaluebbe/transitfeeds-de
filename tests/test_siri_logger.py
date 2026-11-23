from conftest import load

XML = """<?xml version="1.0"?>
<Siri xmlns="http://www.siri.org.uk/siri"><ServiceDelivery>
<ResponseTimestamp>2026-11-23T10:00:00Z</ResponseTimestamp>
<EstimatedTimetableDelivery><EstimatedJourneyVersionFrame>
{journeys}
</EstimatedJourneyVersionFrame></EstimatedTimetableDelivery></ServiceDelivery></Siri>"""

JOURNEY = """<EstimatedVehicleJourney>
<LineRef>{line}</LineRef><DirectionRef>1</DirectionRef>
<FramedVehicleJourneyRef><DataFrameRef>2026-11-23</DataFrameRef>
<DatedVehicleJourneyRef>{id}</DatedVehicleJourneyRef></FramedVehicleJourneyRef>
<PublishedLineName>{line}</PublishedLineName><OperatorRef>{op}</OperatorRef>
<ProductCategoryRef>{cat}</ProductCategoryRef>
<EstimatedCalls>{calls}</EstimatedCalls>
</EstimatedVehicleJourney>"""

CALL = """<EstimatedCall><StopPointRef>{stop}</StopPointRef>
<AimedDepartureTime>2026-11-23T10:05:00Z</AimedDepartureTime>
<ExpectedDepartureTime>2026-11-23T10:06:30Z</ExpectedDepartureTime></EstimatedCall>"""


def journey(id, line, op, cat, stops):
    calls = "".join(CALL.format(stop=s) for s in stops)
    return JOURNEY.format(id=id, line=line, op=op, cat=cat, calls=calls)


def feed():
    return XML.format(journeys="".join([
        journey("21277-0S-8001007-1000", "S1", "0S", "S", ["8098549", "8002553"]),
        journey("11546-800201-1", "RE7", "800201", "RE", ["8002549", "8000199"]),
        journey("3292-8007D5-1", "RE7", "8007D5", "RE", ["8000013"]),
        journey("4711-X-1", "RE1", "X", "RE", ["8000001"]),
    ])).encode()  # fmt: skip


def ids(env, monkeypatch):
    siri = load("loggers/siri_logger.py", "siri_logger", monkeypatch, env)
    ts, journeys = siri.parse(feed())
    assert ts == 1795428000
    return sorted(j["id"].split("-")[0] for j in journeys)


def test_operator_filter(monkeypatch):
    assert ids({"SIRI_OPERATORS": "0S"}, monkeypatch) == ["21277"]


def test_near_categories_need_a_stop_of_the_operator_or_near_stops(monkeypatch):
    env = {"SIRI_OPERATORS": "0S", "SIRI_NEAR_CATEGORIES": "RE", "SIRI_NEAR_STOPS": "8002549"}
    assert ids(env, monkeypatch) == ["11546", "21277"]


def test_line_names(monkeypatch):
    assert ids({"SIRI_OPERATORS": "", "SIRI_LINES": "RE1"}, monkeypatch) == ["4711"]


def test_call_fields(monkeypatch):
    siri = load("loggers/siri_logger.py", "siri_logger", monkeypatch, {"SIRI_OPERATORS": "0S"})
    _, (j,) = siri.parse(feed())
    assert j["calls"][0] == ["8098549", 0, None, None, 1795428300, 1795428390, None, 0]
    assert j["line"] == "S1" and j["cat"] == "S"
