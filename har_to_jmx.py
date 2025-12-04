import json
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

# ------------ НАЛАШТУВАННЯ ------------- #
ALLOWED_METHODS = {"GET", "POST"}
# Додай сюди свої домени (регістро-незалежно)
ALLOWED_DOMAINS = {
    "preprod.ilmakiage.com",
    "quiz-api.preprod.ilmakiage.com",
}

IGNORE_SUBSTRINGS = [
    "google-analytics.com",
    "optimizely",
    "hotjar",
    "logz.io",
    "fonts.gstatic.com",
    "doubleclick.net",
]

# ------------ ДОПОМІЖНІ ФУНКЦІЇ ------------- #

def should_ignore(url: str) -> bool:
    low = url.lower()
    for sub in IGNORE_SUBSTRINGS:
        if sub in low:
            return True
    return False


def is_allowed_domain(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    # прибираємо можливий порт
    if ":" in host:
        host = host.split(":", 1)[0]
    return host in ALLOWED_DOMAINS


def bool_prop(name, value):
    p = ET.Element("boolProp", {"name": name})
    p.text = "true" if value else "false"
    return p


def string_prop(name, value):
    p = ET.Element("stringProp", {"name": name})
    p.text = value
    return p


# ------------ ПОБУДОВА JMX ------------- #

def create_http_sampler(name, url, method, body=None):
    """
    Створює HTTPSamplerProxy елемент для JMeter.
    """
    parsed = urlparse(url)
    protocol = parsed.scheme
    domain = parsed.hostname or ""
    path = parsed.path or "/"
    port = parsed.port or ""

    sampler = ET.Element("HTTPSamplerProxy", {
        "guiclass": "HttpTestSampleGui",
        "testclass": "HTTPSamplerProxy",
        "testname": name,
        "enabled": "true",
    })

    sampler.append(bool_prop("HTTPSampler.postBodyRaw", bool(body)))

    # Arguments (простий варіант — пустий, або body як один параметр)
    element_prop = ET.Element("elementProp", {
        "name": "HTTPsampler.Arguments",
        "elementType": "Arguments",
        "guiclass": "HTTPArgumentsPanel",
        "testclass": "Arguments",
        "enabled": "true",
    })
    collection = ET.Element("collectionProp", {
        "name": "Arguments.arguments"
    })

    if body:
        arg = ET.Element("elementProp", {
            "name": "",
            "elementType": "HTTPArgument",
            "enabled": "true",
        })
        arg.append(bool_prop("HTTPArgument.always_encode", False))
        arg.append(string_prop("Argument.name", "body"))
        arg.append(string_prop("Argument.value", body))
        arg.append(string_prop("Argument.metadata", "="))
        collection.append(arg)

    element_prop.append(collection)
    sampler.append(element_prop)

    sampler.append(string_prop("HTTPSampler.domain", domain))
    sampler.append(string_prop("HTTPSampler.port", str(port)))
    sampler.append(string_prop("HTTPSampler.protocol", protocol))
    sampler.append(string_prop("HTTPSampler.path", path))
    sampler.append(string_prop("HTTPSampler.method", method))
    sampler.append(bool_prop("HTTPSampler.follow_redirects", True))
    sampler.append(bool_prop("HTTPSampler.auto_redirects", False))
    sampler.append(bool_prop("HTTPSampler.use_keepalive", True))
    sampler.append(bool_prop("HTTPSampler.DO_MULTIPART_POST", False))
    sampler.append(bool_prop("HTTPSampler.monitor", False))
    sampler.append(string_prop("HTTPSampler.embedded_url_re", ""))

    return sampler


def build_testplan_from_har(har_path: str, testplan_name: str = "HAR import plan"):
    with open(har_path, "r", encoding="utf-8") as f:
        har = json.load(f)

    entries = har.get("log", {}).get("entries", [])

    # Кореневий елемент JMX
    root = ET.Element("jmeterTestPlan", {
        "version": "1.2",
        "properties": "5.0",
        "jmeter": "5.6.0",
    })
    root_ht = ET.SubElement(root, "hashTree")

    # TestPlan
    testplan = ET.SubElement(root_ht, "TestPlan", {
        "guiclass": "TestPlanGui",
        "testclass": "TestPlan",
        "testname": testplan_name,
        "enabled": "true",
    })
    testplan.append(bool_prop("TestPlan.functional_mode", False))
    testplan.append(bool_prop("TestPlan.tearDown_on_shutdown", True))
    testplan.append(string_prop("TestPlan.comments", "Generated from HAR"))
    testplan.append(string_prop("TestPlan.user_define_classpath", ""))

    testplan_ht = ET.SubElement(root_ht, "hashTree")

    # ThreadGroup
    tg = ET.SubElement(testplan_ht, "ThreadGroup", {
        "guiclass": "ThreadGroupGui",
        "testclass": "ThreadGroup",
        "testname": "HAR Thread Group",
        "enabled": "true",
    })
    tg.append(string_prop("ThreadGroup.num_threads", "1"))
    tg.append(string_prop("ThreadGroup.ramp_time", "1"))
    tg.append(bool_prop("ThreadGroup.scheduler", False))
    tg.append(string_prop("ThreadGroup.duration", ""))
    tg.append(string_prop("ThreadGroup.delay", ""))
    # loop count = 1
    loop = ET.Element("elementProp", {
        "name": "ThreadGroup.main_controller",
        "elementType": "LoopController",
        "guiclass": "LoopControlPanel",
        "testclass": "LoopController",
        "enabled": "true",
    })
    loop.append(bool_prop("LoopController.continue_forever", False))
    loop.append(string_prop("LoopController.loops", "1"))
    tg.append(loop)

    tg_ht = ET.SubElement(testplan_ht, "hashTree")

    # Додаємо HTTP Samplers
    for i, entry in enumerate(entries, start=1):
        req = entry.get("request", {})
        method = req.get("method", "GET").upper()
        url = req.get("url", "")

        if method not in ALLOWED_METHODS:
            continue
        if should_ignore(url):
            continue
        if not is_allowed_domain(url):
            continue

        body = None
        post_data = req.get("postData")
        if post_data and "text" in post_data:
            body = post_data["text"]

        name = f"{i:03d} {method} {url}"
        sampler = create_http_sampler(name, url, method, body)
        tg_ht.append(sampler)
        # Кожен sampler має свій порожній hashTree
        ET.SubElement(tg_ht, "hashTree")

    return root


def save_jmx(root: ET.Element, output_path: str):
    tree = ET.ElementTree(root)
    tree.write(output_path, encoding="UTF-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python har_to_jmx.py input.har output.jmx")
        sys.exit(1)

    har_file = sys.argv[1]
    jmx_file = sys.argv[2]

    root = build_testplan_from_har(har_file, testplan_name="HAR Import Plan")
    save_jmx(root, jmx_file)
    print(f"Saved JMX to {jmx_file}")
