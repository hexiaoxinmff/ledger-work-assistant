"""Bounded PNG/JPEG header preflight shared by local OCR stages."""
import os
import struct
from pathlib import Path
import zlib

MAX_IMAGE_BYTES = 100 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_HEADER_BYTES = 1024 * 1024


def check_image_size(size):
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("图片文件大小无效")
    if size > MAX_IMAGE_BYTES:
        raise ValueError("图片文件超过 100 MiB 上限，未启动 OCR")


def validate_dimensions(width, height):
    if width <= 0 or height <= 0:
        raise ValueError("图片尺寸无效")
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError("图片超过 2500 万像素上限，未启动 OCR")


def png_dimensions(stream):
    if stream.read(8) != b"\x89PNG\r\n\x1a\n":
        raise ValueError("文件内容与 PNG 格式不符")
    chunk = stream.read(25)
    if len(chunk) != 25:
        raise ValueError("PNG 图片头不完整")
    length = struct.unpack(">I", chunk[:4])[0]
    kind, payload, crc_bytes = chunk[4:8], chunk[8:21], chunk[21:25]
    if length != 13 or kind != b"IHDR":
        raise ValueError("PNG 首个数据块不是有效 IHDR")
    expected_crc = struct.unpack(">I", crc_bytes)[0]
    if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
        raise ValueError("PNG 图片头校验失败")
    return struct.unpack(">II", payload[:8])


def jpeg_dimensions(stream):
    if stream.read(2) != b"\xff\xd8":
        raise ValueError("文件内容与 JPEG 格式不符")
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    standalone = {0x01, 0xD8, 0xD9, *range(0xD0, 0xD8)}
    while stream.tell() <= MAX_IMAGE_HEADER_BYTES:
        prefix = stream.read(1)
        if not prefix:
            break
        if prefix != b"\xff":
            raise ValueError("JPEG 图片头标记无效")
        marker_byte = stream.read(1)
        while marker_byte == b"\xff":
            marker_byte = stream.read(1)
        if not marker_byte or marker_byte == b"\x00":
            raise ValueError("JPEG 图片头标记无效")
        marker = marker_byte[0]
        if marker in (0xD9, 0xDA):
            break
        if marker in standalone:
            continue
        length_bytes = stream.read(2)
        if len(length_bytes) != 2:
            raise ValueError("JPEG 图片头不完整")
        segment_length = struct.unpack(">H", length_bytes)[0]
        if segment_length < 2:
            raise ValueError("JPEG 图片头段长度无效")
        payload_length = segment_length - 2
        if stream.tell() + payload_length > MAX_IMAGE_HEADER_BYTES:
            raise ValueError("JPEG 图片头超过 1 MiB 安全上限")
        if marker in sof_markers:
            if payload_length < 5:
                raise ValueError("JPEG 尺寸段不完整")
            frame = stream.read(payload_length)
            if len(frame) != payload_length:
                raise ValueError("JPEG 尺寸段不完整")
            height, width = struct.unpack(">HH", frame[1:5])
            return width, height
        stream.seek(payload_length, os.SEEK_CUR)
    raise ValueError("未在 JPEG 图片头安全范围内找到尺寸信息")


def preflight_image(source):
    """Validate supported image bytes and pixel count using bounded header reads."""
    source = Path(source)
    check_image_size(source.stat().st_size)
    suffix = source.suffix.lower()
    with open(source, "rb") as stream:
        if suffix == ".png":
            dimensions = png_dimensions(stream)
        elif suffix in (".jpg", ".jpeg"):
            dimensions = jpeg_dimensions(stream)
        else:
            raise ValueError("仅支持 PNG/JPEG 图片")
    validate_dimensions(*dimensions)
    return {"width": dimensions[0], "height": dimensions[1]}
