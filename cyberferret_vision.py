import cv2
import numpy as np


class ArucoVision:
    def __init__(self, target_id=7, dictionary_id=cv2.aruco.DICT_4X4_50):
        self.target_id = target_id
        self.dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
        self.parameters = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(
            self.dictionary,
            self.parameters,
        )

    def detect_jpeg(self, jpeg_bytes):
        image_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

        if frame is None:
            return self._not_visible()

        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _rejected = self.detector.detectMarkers(gray)

        if ids is None:
            return self._not_visible()

        for marker_corners, marker_id in zip(corners, ids.flatten()):
            marker_id = int(marker_id)
            if marker_id != self.target_id:
                continue

            points = marker_corners.reshape(4, 2)
            center_x = float(points[:, 0].mean())
            center_y = float(points[:, 1].mean())

            x = (center_x / width) * 2.0 - 1.0
            y = (center_y / height) * 2.0 - 1.0

            top_width = np.linalg.norm(points[1] - points[0])
            bottom_width = np.linalg.norm(points[2] - points[3])
            marker_width = (top_width + bottom_width) / 2.0
            size = float(marker_width / width)

            return {
                "visible": True,
                "id": marker_id,
                "x": float(x),
                "y": float(y),
                "size": size,
            }

        return self._not_visible()

    @staticmethod
    def _not_visible():
        return {
            "visible": False,
            "id": None,
            "x": None,
            "y": None,
            "size": None,
        }
