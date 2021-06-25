from dataclasses import dataclass
from .datasaver import DataSaver


@dataclass
class ChkpContextConfiguration:
    """Chainkeepers configuration object used to transfer
    whatever configuration data within the Mango Explorer Context
    """
    # Oracles API url config
    marinade_api_url: str
    # websocket reconnect config
    reconnect_interval: int = 300
    # DataSaver
    data_saver_dir: str = None
    data_saver_max_observations: int = 5000
    # configuration data for post init
    data_saver: DataSaver = None

    def __post_init__(self):
        if self.data_saver_dir is not None:
            self.data_saver = DataSaver(self.data_saver_dir, self.data_saver_max_observations)
        if self.reconnect_interval is None:
            self.reconnect_interval = 300
