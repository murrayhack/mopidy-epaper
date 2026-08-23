import pathlib

from mopidy import config, ext

__version__ = "0.1.0"


class Extension(ext.Extension):
    dist_name = "Mopidy-Epaper"
    ext_name = "epaper"
    version = __version__

    def get_default_config(self):
        return config.read(pathlib.Path(__file__).parent / "ext.conf")

    def get_config_schema(self):
        schema = super().get_config_schema()
        schema["driver"] = config.String(choices=["epd2in13_v4", "dummy"])
        schema["update_interval"] = config.Integer(minimum=1)
        schema["full_refresh_every"] = config.Integer(minimum=1)
        schema["sleep_after"] = config.Integer(minimum=0)
        schema["idle_screen"] = config.String(choices=["keep", "blank"])
        schema["menu_timeout"] = config.Integer(minimum=0)
        schema["dummy_output_path"] = config.Path(optional=True)
        return schema

    def setup(self, registry):
        from . import http
        from .frontend import EpaperFrontend

        registry.add("frontend", EpaperFrontend)
        registry.add("http:app", {"name": self.ext_name, "factory": http.factory})
