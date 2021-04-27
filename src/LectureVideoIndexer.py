import os
import shutil
import imagehash
import pytesseract
import cv2 as cv

from typing import Optional, Callable, TypedDict
from pathlib import Path
from PIL import Image
from strsimpy.normalized_levenshtein import NormalizedLevenshtein

from Config import Config
from Stage import Stage
from VideoConverter import VideoConverter, CropRegion
from constants import FRAMES_DIR, FRAME_PREFIX

ProgressCallback = Callable[[Stage, float], None]


class VideoIndexEntry(TypedDict):
    second: int
    title: str


VideoIndex = [VideoIndexEntry]


class LectureVideoIndexer:
    config: Config = {
        'frame_step': 2,
        'image_similarity_treshold': 0.9,
        'text_similarity_treshold': 0.85,
        'hash_size': 16,
    }
    progress_callback: ProgressCallback

    __normalized_levenshtein = None

    def __init__(self, config: Optional[Config] = None, progress_callback: ProgressCallback = lambda: None):
        if config is not None:
            self.config = {**self.config, **config}

        self.progress_callback = progress_callback
        self.__normalized_levenshtein = NormalizedLevenshtein()

    def index(self,
              video_path: os.PathLike,
              skip_converting: bool = False,
              crop_region: CropRegion = None) -> VideoIndex:
        if not skip_converting:
            self.__clean()
            self.__convert_to_frames(video_path, crop_region=crop_region)

        _, _, frames = next(os.walk(FRAMES_DIR))
        filtered_frames = self.__filter_similar_frames(frames_count=len(frames))
        index = self.__process_frames(filtered_frames)

        return index

    def __clean(self):
        dirpath = Path(FRAMES_DIR)

        if dirpath.exists() and dirpath.is_dir():
            shutil.rmtree(dirpath)
        dirpath.mkdir(parents=True, exist_ok=True)

    def __convert_to_frames(self, video_path: os.PathLike, crop_region: CropRegion = None):
        converter = VideoConverter(
            self.config['frame_step'],
            progress_callback=lambda progress: self.progress_callback(Stage.CONVERTING, progress))

        converter.convert_to_frames(video_path=video_path, crop_region=crop_region)

    def __filter_similar_frames(self, frames_count: int) -> [int]:
        filtered_frames: [int] = [0]
        prev_frame = 0
        max_frame = frames_count * self.config['frame_step']

        for frame in range(self.config['frame_step'], max_frame, self.config['frame_step']):
            frame_path = self.__create_frame_path(frame)
            similarity = self.__compare_images(self.__create_frame_path(prev_frame), frame_path)

            if (similarity < self.config['image_similarity_treshold']):
                filtered_frames.append(frame)
            prev_frame = frame

            progress = round((frame + 1) / max_frame * 100)
            self.progress_callback(Stage.FILTERING, progress)

        return filtered_frames

    def __compare_images(self, img_path_a: os.PathLike, img_path_b: os.PathLike) -> float:
        hash_a = imagehash.phash(Image.open(img_path_a), hash_size=self.config['hash_size'])
        hash_b = imagehash.phash(Image.open(img_path_b), hash_size=self.config['hash_size'])

        return self.__normalized_levenshtein.similarity(str(hash_a), str(hash_b))

    def __process_frames(self, frames: [int]) -> VideoIndex:
        index: VideoIndex = []
        prev_title: str = None

        for i in range(len(frames)):
            frame = frames[i]
            frame_path = self.__create_frame_path(frame)
            image = self.__preprocess_image(frame_path)

            text = pytesseract.image_to_string(image)
            title = self.__extract_title(text)

            if prev_title and title:
                similarity = self.__normalized_levenshtein.similarity(prev_title, title)

                if similarity < self.config['text_similarity_treshold']:
                    entry: VideoIndexEntry = {'second': frame, 'title': title}
                    index.append(entry)
            elif not prev_title and title:
                entry: VideoIndexEntry = {'second': frame, 'title': title}
                index.append(entry)

            if title:
                prev_title = title
            self.progress_callback(Stage.PROCESSING, round(((i + 1) * 100) / len(frames)))

        return index

    def __preprocess_image(self, path: os.PathLike):
        img = cv.imread(path)

        img = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
        img = cv.medianBlur(img, 3)
        thresholded_img = cv.adaptiveThreshold(img, 255, cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY, 11,
                                               2)

        return thresholded_img

    def __extract_title(self, text) -> str:
        lines = [line for line in text.strip().split('\n') if not line.isspace() and len(line) > 1]
        title = lines[0] if lines else None

        return title

    def __create_frame_path(self, frame) -> str:
        return os.path.join(FRAMES_DIR, f"{FRAME_PREFIX}{frame}.png")
