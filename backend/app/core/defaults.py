"""
DEFAULTS: 추출 실패 시 null → merge 후 source: "default" 기록.
brand 필드에만 적용. 소방/시공 수치는 하드코딩 (space_data.py 참조).
"""

DEFAULTS: dict = {
    "brand": {
        "clearspace_mm": {
            "value": 1500,
            "confidence": "low",
            "source": "default",
        },
        "logo_clearspace_mm": {
            "value": 300,
            "confidence": "low",
            "source": "default",
        },
        "character_orientation": {
            "value": None,
            "confidence": "low",
            "source": "default",
        },
        "prohibited_material": {
            "value": None,
            "confidence": "low",
            "source": "default",
        },
    },
    "floor": {
        "ceiling_height_mm": {
            "value": 3000,
            "confidence": "low",
            "source": "default",
        },
    },
}


def merge_with_defaults(space_data: dict) -> dict:
    """
    space_data의 null 필드를 DEFAULTS로 채운다.
    이미 값이 있는 필드는 덮어쓰지 않는다.
    """
    for section, fields in DEFAULTS.items():
        if section not in space_data:
            space_data[section] = {}
        for key, default_val in fields.items():
            if space_data[section].get(key) is None:
                space_data[section][key] = default_val
    return space_data
