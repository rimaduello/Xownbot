# flake8: noqa
__all__ = ["example"]

# Don't look below, you will not understand this Python code :) I don't.

from js2py.pyjs import *

# setting scope
var = Scope(JS_BUILTINS)
set_global_object(var)

# Code follows:
var.registers([])


@Js
def PyJs_anonymous_0_(e, this, arguments, var=var):
    var = Scope({"e": e, "this": this, "arguments": arguments}, var)
    var.registers(["l", "r", "i", "t", "n", "a", "e", "o", "s"])
    var.put(
        "t",
        Js(
            "АВСDЕFGHIJKLМNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,~"
        ),
    )
    var.put("n", Js(""))
    var.put("r", Js(0.0))
    PyJsComma(
        (
            JsRegExp("/[^АВСЕМA-Za-z0-9\\.\\,\\~]/g").callprop(
                "exec", var.get("e")
            )
            and var.get("console").callprop("log", Js("error decoding url"))
        ),
        var.put(
            "e",
            var.get("e").callprop(
                "replace", JsRegExp("/[^АВСЕМA-Za-z0-9\\.\\,\\~]/g"), Js("")
            ),
        ),
    )
    while 1:
        var.put(
            "a",
            var.get("t").callprop(
                "indexOf",
                var.get("e").callprop(
                    "charAt",
                    (
                        var.put("r", Js(var.get("r").to_number()) + Js(1))
                        - Js(1)
                    ),
                ),
            ),
        )
        var.put(
            "i",
            var.get("t").callprop(
                "indexOf",
                var.get("e").callprop(
                    "charAt",
                    (
                        var.put("r", Js(var.get("r").to_number()) + Js(1))
                        - Js(1)
                    ),
                ),
            ),
        )
        var.put(
            "o",
            var.get("t").callprop(
                "indexOf",
                var.get("e").callprop(
                    "charAt",
                    (
                        var.put("r", Js(var.get("r").to_number()) + Js(1))
                        - Js(1)
                    ),
                ),
            ),
        )
        var.put(
            "l",
            var.get("t").callprop(
                "indexOf",
                var.get("e").callprop(
                    "charAt",
                    (
                        var.put("r", Js(var.get("r").to_number()) + Js(1))
                        - Js(1)
                    ),
                ),
            ),
        )
        PyJsComma(
            var.put(
                "a", ((var.get("a") << Js(2.0)) | (var.get("i") >> Js(4.0)))
            ),
            var.put(
                "i",
                (
                    ((Js(15.0) & var.get("i")) << Js(4.0))
                    | (var.get("o") >> Js(2.0))
                ),
            ),
        )
        var.put("s", (((Js(3.0) & var.get("o")) << Js(6.0)) | var.get("l")))
        PyJsComma(
            PyJsComma(
                var.put(
                    "n",
                    var.get("String").callprop("fromCharCode", var.get("a")),
                    "+",
                ),
                (
                    (Js(64.0) != var.get("o"))
                    and var.put(
                        "n",
                        var.get("String").callprop(
                            "fromCharCode", var.get("i")
                        ),
                        "+",
                    )
                ),
            ),
            (
                (Js(64.0) != var.get("l"))
                and var.put(
                    "n",
                    var.get("String").callprop("fromCharCode", var.get("s")),
                    "+",
                )
            ),
        )
        if not (var.get("r") < var.get("e").get("length")):
            break
    return var.get("unescape")(var.get("n"))


PyJs_anonymous_0_._set_name("anonymous")
var.put("d", PyJs_anonymous_0_)
pass


# Add lib to the module scope
example = var.to_python()
decode = example.d
