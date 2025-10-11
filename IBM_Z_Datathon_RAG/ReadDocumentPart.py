#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
read_document_part.py

Retrieve a specific part of an XML document by ID.
Supports both DOM parsing (fast, for small/medium files) and streaming (memory-efficient for huge files).
"""

import sys
from copy import deepcopy
from typing import Optional
from lxml import etree


# ------------------------------
# Helpers
# ------------------------------
def derive_doc_id(part_id: str, root: Optional[etree._Element] = None) -> str:
    """
    Derive a document identifier for display/tracking.
    Default: take the prefix before the first dot in part_id (e.g., "Marbury_v_Madison" from "Marbury_v_Madison.Facts.p002").
    Fallbacks try to read something meaningful from the XML if provided.
    """
    if "." in part_id:
        return part_id.split(".", 1)[0]
    if root is not None:
        case = root.find(".//Case")
        if case is not None:
            for key in ("name", "title", "id"):
                val = case.get(key)
                if val:
                    return val.replace(" ", "_")
    return "unknown_doc"


def wrap_subtree(node: etree._Element, part_id: str, doc_id: str) -> etree._Element:
    """
    Wrap the matched node in a lightweight envelope that mirrors the slides' display style.
    """
    legal = etree.Element("legalDocument", lang="en", docId=doc_id)
    part = etree.SubElement(legal, "part", partId=part_id)
    part.append(node)
    return legal


# ------------------------------
# DOM version (simple and fast)
# ------------------------------
def read_document_part_dom(xml_path: str, part_id: str, wrap: bool = True) -> str:
    """
    Parse the entire XML into memory and return the matched node's subtree as a Unicode string.
    Best for small/medium files.
    """
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(xml_path, parser)
    root = tree.getroot()

    # XPath: any element with attribute id == part_id
    nodes = root.xpath("//*[@id=$pid]", pid=part_id)
    if not nodes:
        raise KeyError(f"part_id not found: {part_id}")

    # Copy the node so we can safely reparent/wrap without touching the original tree
    node_copy = deepcopy(nodes[0])

    if wrap:
        doc_id = derive_doc_id(part_id, root)
        wrapped = wrap_subtree(node_copy, part_id, doc_id)
        return etree.tostring(wrapped, encoding="unicode", pretty_print=True)

    return etree.tostring(node_copy, encoding="unicode", pretty_print=True)


# ------------------------------
# Streaming version (memory-light)
# ------------------------------
def read_document_part_stream(xml_path: str, part_id: str, wrap: bool = True) -> str:
    """
    Stream through the XML and emit the first element whose @id == part_id.
    Uses minimal memory; suitable for very large XML files.
    """
    context = etree.iterparse(xml_path, events=("start", "end"), remove_blank_text=True)
    root_for_doc_id: Optional[etree._Element] = None

    found = False
    build_stack = []           # stack of constructed (copied) nodes
    built_root: Optional[etree._Element] = None  # the root of the copied subtree

    for event, elem in context:
        if root_for_doc_id is None and event == "start":
            root_for_doc_id = elem.getroottree().getroot()

        if event == "start":
            if not found:
                if elem.get("id") == part_id:
                    found = True
                    node = etree.Element(elem.tag, **{k: v for k, v in elem.items()})
                    if elem.text:
                        node.text = elem.text
                    build_stack.append(node)
                    built_root = node
            else:
                node = etree.Element(elem.tag, **{k: v for k, v in elem.items()})
                if elem.text:
                    node.text = elem.text
                build_stack[-1].append(node)
                build_stack.append(node)

        else:  # event == "end"
            if found:
                # Preserve tail text for the last constructed node
                if elem.tail and build_stack:
                    if build_stack[-1].tail:
                        build_stack[-1].tail += elem.tail
                    else:
                        build_stack[-1].tail = elem.tail

                # When closing a tag, pop the construction stack if it matches
                if build_stack and elem.tag == build_stack[-1].tag:
                    build_stack.pop()

                # If we closed the original matched element, we can stop
                if elem.get("id") == part_id and not build_stack:
                    break

            # Free memory for elements outside our constructed subtree
            if not found:
                elem.clear()

    if built_root is None:
        raise KeyError(f"part_id not found: {part_id}")

    if wrap:
        doc_id = derive_doc_id(part_id, root_for_doc_id)
        wrapped = wrap_subtree(built_root, part_id, doc_id)
        return etree.tostring(wrapped, encoding="unicode", pretty_print=True)

    return etree.tostring(built_root, encoding="unicode", pretty_print=True)


# ------------------------------
# Main function
# ------------------------------
def read_document_part(
    xml_file: str,
    part_id: str,
    wrap: bool = True,
    stream: bool = False
) -> str:
    """
    Retrieve a specific part of an XML document by its ID.
    
    Args:
        xml_file: Path to the XML file (e.g., "./normalized_enhanced.xml")
        part_id: The ID of the element to retrieve (e.g., "Marbury_v_Madison.Facts.p002")
        wrap: Whether to wrap the result in a legalDocument/part envelope (default: True)
        stream: Use streaming parser for large files (slower but memory-efficient). Default: False (fast DOM parsing)
    
    Returns:
        XML-formatted result as a Unicode string
    
    Raises:
        KeyError: If part_id is not found in the XML
        Exception: If XML parsing fails
    """
    try:
        if stream:
            return read_document_part_stream(xml_file, part_id, wrap=wrap)
        else:
            return read_document_part_dom(xml_file, part_id, wrap=wrap)
    except Exception as e:
        raise Exception(f"[ERROR] {e}")


if __name__ == "__main__":
    # Example usage:
    result = read_document_part(
        "./normalized_enhanced.xml",
        "Marbury_v_Madison.Facts.p002",
        wrap=True,
        stream=False
    )
    print(result)
