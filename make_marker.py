import cv2
import numpy as np


OUTPUT_PATH = "/home/jesse/marker-7.png"
MARKER_ID = 7
MARKER_SIZE = 700
MARGIN = 200

dictionary = cv2.aruco.getPredefinedDictionary(
    cv2.aruco.DICT_4X4_50
)

marker = cv2.aruco.generateImageMarker(
    dictionary,
    MARKER_ID,
    MARKER_SIZE,
)

canvas_size = MARKER_SIZE + (MARGIN * 2)
canvas = np.full(
    (canvas_size, canvas_size),
    255,
    dtype=np.uint8,
)

canvas[
    MARGIN:MARGIN + MARKER_SIZE,
    MARGIN:MARGIN + MARKER_SIZE
] = marker

cv2.imwrite(OUTPUT_PATH, canvas)
print(f"Created {OUTPUT_PATH}")
