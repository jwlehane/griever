from abc import ABC, abstractmethod

class CountyInterface(ABC):
    """
    Abstract Base Class for County ParcelAccess integrations.
    Ensures that adding new counties (like Ulster) follows a standard interface.
    """
    
    @abstractmethod
    def search_address(self, address_string: str) -> dict:
        """
        Searches for a property by address. 
        Returns a dict with basic info (at least 'parcelgrid' or equivalent ID) or None.
        """
        pass

    @abstractmethod
    def get_full_rps_data(self, identifier: str) -> dict:
        """
        Retrieves full Real Property Services (RPS) data using a unique identifier.
        Returns a standardized dict of property characteristics.
        """
        pass

    @abstractmethod
    def get_town_from_identifier(self, identifier: str) -> str:
        """
        Extracts or maps the town name from the property identifier (e.g. SWIS prefix).
        Used for market discovery.
        """
        pass
