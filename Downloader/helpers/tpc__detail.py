# flake8: noqa
__all__ = ["tcp__detail"]

# Don't look below, you will not understand this Python code :) I don't.

from js2py.pyjs import *

# setting scope
var = Scope(JS_BUILTINS)
set_global_object(var)

# Code follows:
var.registers(["video"])


@Js
def PyJsHoisted_video_(lifetime, video_id, this, arguments, var=var):
    var = Scope(
        {
            "lifetime": lifetime,
            "video_id": video_id,
            "this": this,
            "arguments": arguments,
        },
        var,
    )
    var.registers(["i", "video_id", "lifetime", "s"])
    var.put(
        "lifetime",
        (
            Js(86400.0)
            if (var.get("null") == var.get("lifetime"))
            else var.get("lifetime")
        ),
    )
    var.put(
        "s",
        (
            (
                (
                    Js(1000000.0)
                    * var.get("Math").callprop(
                        "floor", (var.get("video_id") / Js(1000000.0))
                    )
                )
                + Js("/")
            )
            + (
                Js(1000.0)
                * var.get("Math").callprop(
                    "floor", (var.get("video_id") / Js(1000.0))
                )
            )
        ),
    )
    var.put("i", (Js("json") if var.get("lifetime") else Js("jsond")))
    return (
        (
            (
                (
                    ((Js("/api/json/video/") + var.get("lifetime")) + Js("/"))
                    + var.get("s")
                )
                + Js("/")
            )
            + var.get("video_id")
        )
        + Js(".")
    ) + var.get("i")


PyJsHoisted_video_.func_name = "video"
var.put("video", PyJsHoisted_video_)
pass
pass


# Add lib to the module scope
tcp__detail = var.to_python()
detail = tcp__detail.video
