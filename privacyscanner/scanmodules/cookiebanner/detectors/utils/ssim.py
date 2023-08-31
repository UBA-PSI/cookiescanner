import cv2
import numpy

from skimage.metrics import structural_similarity as compare_ssim


def compare_images(image1: numpy.ndarray, image2: numpy.ndarray) -> float:
    """Calculates and returns the structural similarity of two provided images."""
    if image1 is None or image2 is None:
        return 0
    image1 = cv2.cvtColor(image1, cv2.COLOR_BGR2GRAY)
    image1_height, image1_width = image1.shape
    image2 = cv2.cvtColor(image2, cv2.COLOR_BGR2GRAY)
    image2_height, image2_width = image2.shape
    if image1_height == image2_height and image1_width == image2_width:
        (score, diff) = compare_ssim(image1, image2, full=True)
        diff = (diff * 255).astype("uint8")
    else:
        score = None
    return score


def truncate_image_width(image1: numpy.ndarray, image2: numpy.ndarray) -> numpy.ndarray and numpy.ndarray:
    """The function takes two images as numpy array and adjust the dimensions to match the smaller one if one image is
    wider than the other. Returns the images as numpy arrays."""
    # 0: height; 1: width
    if image2.shape[1] < image1.shape[1]:
        image1 = image1[0:image2.shape[0], 0: image2.shape[1]]
    if image2.shape[1] > image1.shape[1]:
        image2 = \
            image2[0:image1.shape[1], 0: image1.shape[1]]
    return image1, image2


def calculate_ssim_score(image1: numpy.ndarray, image2: numpy.ndarray) -> float or None:
    # Truncate screenshots in case one is wider than the other (e.g. because of a scroll bar)
    image1, image2 = truncate_image_width(image1=image1, image2=image2)
    # Calculate ssim score
    ssim = compare_images(image1=image1, image2=image2)
    if ssim:
        ssim = ssim
    else:
        ssim = None
    return ssim
