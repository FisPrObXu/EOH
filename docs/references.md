# Technical References

The implementation uses conservative, classical computer-vision methods inspired by openly documented tools and examples:

- scikit-image documentation for thresholding, morphology, connected-component measurements, ORB features, RANSAC models, and region properties: https://scikit-image.org/docs/stable/
- OpenCV documentation for feature matching and homography concepts where OpenCV is available as an optional backend: https://docs.opencv.org/
- Petrographic image segmentation examples using PPL/XPL imagery as a multi-image petrographic context: https://github.com/jbardelli/Petrographic-Image-Segmentation
- Deep mineralogical segmentation work showing why final mineral classification should be training-data driven and validated, not asserted from a single heuristic pass: https://github.com/ltracegeo/deep-mineralogical-segmentation

In this project these references are used for workflow design only. Mineral names remain conservative candidates unless confirmed by manual petrography and/or laboratory measurements.
