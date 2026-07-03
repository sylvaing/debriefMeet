"""Énumération des GPU Vulkan via le loader du driver (ctypes), sans SDK ni binaire.

⚠ Conçu pour être lancé en SOUS-PROCESSUS (`python -m spike.backends_windows.vulkan_probe`) :
un éventuel segfault driver ne tue que l'enfant, jamais le spike principal.
"""
from __future__ import annotations

import ctypes
import json
import sys

FABRICANTS = {
    0x8086: "intel",
    0x1002: "amd",
    0x10DE: "nvidia",
    0x13B5: "arm",
    0x5143: "qualcomm",
    0x1010: "imgtec",
    0x106B: "apple",
}

TYPES = {0: "autre", 1: "integrated", 2: "discrete", 3: "virtual", 4: "cpu"}

VK_SUCCESS = 0
VK_STRUCTURE_TYPE_APPLICATION_INFO = 0
VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1


class _VkApplicationInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("_pad0", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("pApplicationName", ctypes.c_char_p),
        ("applicationVersion", ctypes.c_uint32),
        ("_pad1", ctypes.c_uint32),
        ("pEngineName", ctypes.c_char_p),
        ("engineVersion", ctypes.c_uint32),
        ("apiVersion", ctypes.c_uint32),
    ]


class _VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("_pad0", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("_pad1", ctypes.c_uint32),
        ("pApplicationInfo", ctypes.c_void_p),
        ("enabledLayerCount", ctypes.c_uint32),
        ("_pad2", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("_pad3", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]


class _VkPhysicalDeviceProperties(ctypes.Structure):
    _fields_ = [
        ("apiVersion", ctypes.c_uint32),
        ("driverVersion", ctypes.c_uint32),
        ("vendorID", ctypes.c_uint32),
        ("deviceID", ctypes.c_uint32),
        ("deviceType", ctypes.c_uint32),
        ("deviceName", ctypes.c_char * 256),
        ("pipelineCacheUUID", ctypes.c_uint8 * 16),
        ("_reste", ctypes.c_uint8 * 2048),
    ]


def _charger_loader() -> ctypes.CDLL:
    if sys.platform == "win32":
        noms = ["vulkan-1.dll"]
    elif sys.platform == "darwin":
        noms = ["libvulkan.dylib", "libvulkan.1.dylib", "libMoltenVK.dylib"]
    else:
        noms = ["libvulkan.so.1", "libvulkan.so"]
    derniere = None
    for nom in noms:
        try:
            return ctypes.CDLL(nom)
        except OSError as exc:
            derniere = exc
    raise OSError(f"loader Vulkan introuvable ({noms}) : {derniere}")


def _version(v: int) -> str:
    return f"{(v >> 22) & 0x3FF}.{(v >> 12) & 0x3FF}.{v & 0xFFF}"


def enumerer() -> list[dict]:
    vk = _charger_loader()

    app = _VkApplicationInfo()
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO
    app.pApplicationName = b"debriefMeet-spike"
    app.apiVersion = (1 << 22)

    info = _VkInstanceCreateInfo()
    info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
    info.pApplicationInfo = ctypes.cast(ctypes.byref(app), ctypes.c_void_p)

    instance = ctypes.c_void_p()
    if vk.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance)) != VK_SUCCESS:
        raise RuntimeError("vkCreateInstance a échoué")

    try:
        count = ctypes.c_uint32(0)
        if vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None) != VK_SUCCESS:
            raise RuntimeError("vkEnumeratePhysicalDevices (count) a échoué")
        n = count.value
        if n == 0:
            return []
        devices = (ctypes.c_void_p * n)()
        if vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices) != VK_SUCCESS:
            raise RuntimeError("vkEnumeratePhysicalDevices (liste) a échoué")

        gpus: list[dict] = []
        for i in range(n):
            props = _VkPhysicalDeviceProperties()
            vk.vkGetPhysicalDeviceProperties(devices[i], ctypes.byref(props))
            gpus.append({
                "nom": props.deviceName.decode("utf-8", "replace").strip("\x00").strip(),
                "type": TYPES.get(props.deviceType, "autre"),
                "fabricant": FABRICANTS.get(props.vendorID, f"0x{props.vendorID:04x}"),
                "api_version": _version(props.apiVersion),
            })
        return gpus
    finally:
        try:
            vk.vkDestroyInstance(instance, None)
        except Exception:
            pass


def main() -> int:
    try:
        print(json.dumps(enumerer()))
        return 0
    except Exception as exc:
        print(json.dumps({"erreur": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
