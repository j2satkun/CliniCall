# external services for address validation and emails
from datetime import datetime
import logging
import os
from typing import Tuple, Dict, Optional

import aiohttp


class AddressValidator:
    def __init__(self):
        self.api_key = os.getenv("HERE_API_KEY")
        self.base_url = "https://geocode.search.hereapi.com/v1/geocode"

    async def validate(self, address_data: Dict) -> Tuple[bool, Optional[Dict]]:
        try:
            address_parts = []
            if address_data.get("line1"):
                address_parts.append(address_data["line1"])
            if address_data.get("line2"):
                address_parts.append(address_data["line2"])
            if address_data.get("city"):
                address_parts.append(address_data["city"])
            if address_data.get("state"):
                address_parts.append(address_data["state"])
            if address_data.get("zip_code"):
                address_parts.append(address_data["zip_code"])

            address_string = ", ".join(address_parts)

            params = {"q": address_string, "apiKey": self.api_key, "limit": 1}

            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()

                        if data.get("items") and len(data["items"]) > 0:
                            item = data["items"][0]
                            address = item.get("address", {})

                            validated = {
                                "line1": address.get("houseNumber", "")
                                + " "
                                + address.get("street", ""),
                                "line2": address_data.get("line2", ""),
                                "city": address.get("city", ""),
                                "state": address.get("state", ""),
                                "zip_code": address.get("postalCode", ""),
                            }

                            return True, validated
                        else:
                            return False, None
                    else:
                        logging.error(f"HERE API error: {response.status}")
                        return False, None

        except Exception as e:
            logging.error(f"Address validation error: {e}")
            return False, None
