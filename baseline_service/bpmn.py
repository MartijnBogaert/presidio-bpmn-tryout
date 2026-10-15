import xml.etree.ElementTree as ET


def extract_elem_from_bpmn(bpmn_content) -> list:
    elements = []
    root = ET.fromstring(bpmn_content)
    try:
        for elem in root.iter():
            if "name" in elem.attrib:
                elements.append(
                    {
                        "id": elem.attrib.get("id", ""),
                        "name": elem.attrib["name"].strip(),
                    }
                )
        return list(elements)

    except ET.ParseError as e:
        raise ValueError(f"Invalid BPMN XML format: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error processing BPMN file: {str(e)}")


def get_element_name(root: ET.Element, element_id: str) -> str:
    el = root.find(f".//*[@id='{element_id}']")
    return el.attrib.get("name", "").strip() if el is not None else ""


def set_element_name(root: ET.Element, element_id: str, new_name: str):
    el = root.find(f".//*[@id='{element_id}']")
    if el is not None and "name" in el.attrib:
        el.attrib["name"] = new_name


def deserialize_bpmn(file):
    return ET.fromstring(file.read().decode("utf-8"))


def serialize_bpmn(root: ET.Element) -> str:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
