import re

def parse_trade_signal(message_content):
    """
    Parses a trade signal from a message string.
    Expected approximate format: BTCUSDT long / short Entry: ... sl: ... TP: ...
    Returns a dict with pair, direction, entry, sl, tp if successful, else None.
    """
    # Clean up the message for easier regex matching (remove formatting like ** or __)
    content = message_content.replace('*', '').replace('_', '').upper()
    
    # Try to find Pair and Direction
    # Example matches: BTCUSDT LONG, ETH/USDT SHORT
    pair_direction_match = re.search(r'([A-Z0-9]{2,10}/?[A-Z0-9]{2,6})\s+(LONG|SHORT)', content)
    
    if not pair_direction_match:
        # Maybe direction comes first: LONG BTCUSDT
        pair_direction_match = re.search(r'(LONG|SHORT)\s+([A-Z0-9]{2,10}/?[A-Z0-9]{2,6})', content)
        if not pair_direction_match:
            return None
        direction = pair_direction_match.group(1)
        pair = pair_direction_match.group(2)
    else:
        pair = pair_direction_match.group(1)
        direction = pair_direction_match.group(2)
        
    # Extract prices using flexible regex
    entry_match = re.search(r'(?:ENTRY|@M?)\s*[:\-]?\s*([\d\.]+)', content)
    sl_match = re.search(r'SL\s*[:\-]?\s*([\d\.]+)', content)
    tp_match = re.search(r'TP\s*[:\-]?\s*([\d\.]+)', content)
    
    if entry_match and sl_match and tp_match:
        return {
            'pair': pair.replace('/', ''),
            'direction': direction,
            'entry': float(entry_match.group(1)),
            'sl': float(sl_match.group(1)),
            'tp': float(tp_match.group(1))
        }
    
    return None
