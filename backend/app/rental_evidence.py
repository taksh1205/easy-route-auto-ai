"""Extract supported rental facts from retrieved chunks. Each rule names its evidence sentence."""

import re

# Rules specify the supported question and the required words in the actual passage.
FACTS = [
    ("rental_pickup", r"pickup|pick up|keys|collect|meet", "coordinate a meeting time"),
    (
        "rental_terms",
        r"\bquote(?:s)?\b.*(?:expir|last|valid)|how long.*\bquotes?\b",
        "Quotes expire in fifteen minutes",
    ),
    (
        "rental_terms",
        r"leftover|extra days|partial|balance|remaining|daily rate|whole month",
        "Remaining days use the listed daily rate",
    ),
    (
        "rental_terms",
        r"deposit|tax|insurance payment",
        "No tax, deposit or insurance payment",
    ),
    ("rental_changes", r"conflict|overlap", "original reservation stays active"),
    (
        "rental_changes",
        r"extend|extension|add nights|extra nights",
        "new extension quote and staff review",
    ),
    ("rental_changes", r"cancel|call off", "Staff may cancel a confirmed reservation"),
    ("rental_terms", r"include|inclusions", "include vehicle use only"),
    (
        "rental_documents",
        r"bring|required documents",
        "Ask staff which documents to bring",
    ),
    (
        "rental_documents",
        r"submit|upload|send|scans",
        "Do not upload identity documents",
    ),
]

# Closed vocabulary for affirmative answers. Unrecognized qualifiers go to staff.
POLICY_WORDS = set(
    [
        "a",
        "an",
        "the",
        "i",
        "my",
        "we",
        "our",
        "you",
        "your",
        "is",
        "are",
        "do",
        "does",
        "can",
        "should",
        "will",
        "to",
        "at",
        "on",
        "from",
        "by",
        "with",
        "after",
        "before",
        "of",
        "for",
        "in",
        "if",
        "how",
        "who",
        "what",
        "which",
        "when",
        "where",
        "me",
        "us",
        "it",
        "that",
        "this",
        "someone",
        "else's",
        "their",
        "happens",
        "someone",
        "else",
        "plans",
        "change",
        "get",
        "saying",
        "explain",
        "tell",
        "please",
        "about",
        "synthetic",
        "rental",
        "reservation",
        "request",
        "vehicle",
        "actual",
        "original",
        "active",
        "pending",
        "approved",
        "confirmed",
        "staff",
        "approves",
        "approve",
        "coordinates",
        "coordinate",
        "meeting",
        "meet",
        "pickup",
        "pick",
        "up",
        "keys",
        "collect",
        "collection",
        "desk",
        "procedure",
        "process",
        "location",
        "tempe",
        "extend",
        "extension",
        "nights",
        "add",
        "extra",
        "days",
        "conflict",
        "conflicts",
        "overlapping",
        "overlap",
        "overlaps",
        "billing",
        "billed",
        "balance",
        "left",
        "leftover",
        "remaining",
        "after",
        "whole",
        "full",
        "calendar",
        "month",
        "months",
        "partial",
        "charged",
        "rate",
        "applies",
        "apply",
        "daily",
        "costs",
        "cost",
        "quote",
        "expire",
        "expires",
        "long",
        "last",
        "lasts",
        "valid",
        "include",
        "includes",
        "cash",
        "deposit",
        "tax",
        "insurance",
        "payment",
        "cancel",
        "cancellation",
        "confirm",
        "submit",
        "scan",
        "scans",
        "documents",
        "document",
        "send",
        "upload",
        "driver's",
        "driving",
        "license",
        "identity",
        "chat",
        "proof",
        "paperwork",
        "policy",
        "policies",
        "required",
        "bring",
        "needed",
        "requirements",
        "rental",
        "car",
        "included",
        "inclusions",
    ]
)

DETAILS = [
    (
        r"\b(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m|p\.?m)|\d{1,2}:\d{2}|midnight|noon|hours|overnight|weekends?|sundays?|saturdays?|late at night)\b",
        "the requested time or opening hours",
    ),
    (
        r"fee|surcharge|penalt|refund|discount|waiv|reimburs|free of charge",
        "the requested fee, refund or exception",
    ),
    (
        r"roommate|someone else|third.party|on my behalf|friend|spouse|partner|without approval|without staff|unattended|underage|pets?|animals?",
        "the requested permission or exception",
    ),
    (
        r"which (?:id|license|documents?).*(?:accepted|valid)|passport|international licen[cs]e",
        "the specific document's eligibility",
    ),
    (r"airport|flight|air miles|rewards", "airport or travel arrangements"),
]


def assess(query, hits):
    citations = []
    missing = []
    for clause in re.split(r"\s+(?:and|also)\s+|[;?]", query.casefold()):
        clause = clause.strip(" .,")
        if not clause:
            continue
        if re.search(r"\b(?:reservation|booking)\b", clause) and re.search(
            r"expir|how long.*valid", clause
        ):
            missing.append("which reservation you mean and its recorded return date")
            continue
        # A competing booking describes occupancy. It does not grant another
        # person permission to collect or operate a vehicle.
        clause = re.sub(r"someone else['’]s (?:booking|reservation)\b", "reservation", clause)
        gaps = [label for pattern, label in DETAILS if re.search(pattern, clause)]
        if re.search(r"\bhow much\b|\$\s*\d|\b(?:cost|price|amount)\b", clause):
            gaps.append("the exact amount or fee")
        if re.search(r"\bwhen\b|\bhow (?:early|late|long)\b", clause) and re.search(
            r"pickup|pick up|keys|collect", clause
        ):
            gaps.append("the requested pickup time")
        if re.search(r"\d", clause) and not gaps:
            gaps.append("the requested numeric detail")
        if gaps:
            missing.extend(gaps)
            continue
        if set(re.findall(r"[a-z]+(?:'[a-z]+)?", clause)) - POLICY_WORDS:
            missing.append(clause)
            continue
        matches = [
            (topic, anchor) for topic, pattern, anchor in FACTS if re.search(pattern, clause)
        ]
        # Extra days in a conflict question concern occupancy, not daily pricing.
        if re.search(r"conflict|overlap", clause):
            matches = [m for m in matches if "original reservation" in m[1]]
        # A question about whether a transaction or special arrangement is permitted
        # needs an express policy. Merely mentioning a rental topic cannot establish it.
        if re.match(r"(?:may|can|could|would)\b", clause) and not re.search(
            r"(?:send|upload)|(?:how|where).*", clause
        ):
            matches = []
        if not matches:
            missing.append(clause)
            continue
        for topic, anchor in matches:
            found = None
            for hit in hits:
                if hit["doc_id"] != topic:
                    continue
                sentence = next(
                    (
                        s.strip()
                        for s in re.split(r"(?<=\.)\s+", hit["text"])
                        if anchor.casefold() in s.casefold()
                    ),
                    None,
                )
                if sentence:
                    found = {**hit, "text": sentence}
                    break
            if found is None:
                missing.append(clause)
            elif found not in citations:
                citations.append(found)
    return citations, list(dict.fromkeys(missing))
