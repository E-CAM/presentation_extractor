FROM clowder/pyclowder:2

MAINTAINER Ward Poelmans <wpoely86@gmail.com>

# Setup environment variables. These are passed into the container. You can change
# these to your setup. If RABBITMQ_URI is not set, it will try and use the rabbitmq
# server that is linked into the container. MAIN_SCRIPT is set to the script to be
# executed by entrypoint.sh
# REGISTRATION_ENDPOINTS should point to a central clowder instance, for example it
# could be https://clowder.ncsa.illinois.edu/clowder/api/extractors?key=secretKey
ENV RABBITMQ_URI="" \
    RABBITMQ_EXCHANGE="clowder" \
    RABBITMQ_QUEUE="ncsa.videopresentation" \
    REGISTRATION_ENDPOINTS="https://clowder.ncsa.illinois.edu/extractors" \
    MAIN_SCRIPT="video-presentation.py"

# Install any programs needed
RUN apt-get update && apt-get install -y \
     ffmpeg libavcodec-dev libavfilter-dev libavformat-dev \
     python-pip \
     python2.7-dev cmake git pkg-config wget build-essential && \
     apt-get -y build-dep python-opencv && \
     rm -rf /var/lib/apt/lists/*

RUN wget -O opencv.tar.gz https://github.com/opencv/opencv/archive/3.3.1.tar.gz && \
    tar -xvzf opencv.tar.gz && \
    cd opencv-* && \
    mkdir build && \
    cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr -D BUILD_PYTHON_SUPPORT=ON -DWITH_FFMPEG=ON .. && \
    make -j4 && \
    make install && \
    cd ../.. && \
    rm -rf opencv-*

# This provides a recent version of OpenCV
#RUN pip install -U opencv-contrib-python

# Until our PR is merged in master, install manually (not required if not using sections)
# https://opensource.ncsa.illinois.edu/bitbucket/projects/CATS/repos/pyclowder2/pull-requests/55/overview
#RUN pip install -U git+https://github.com/wpoely86/pyclowder2.git@feature/upload_section_description

# Switch to clowder, copy files and be ready to run
USER clowder

# command to run when starting docker
COPY entrypoint.sh *.py extractor_info.json /home/clowder/
RUN mkdir /home/clowder/config
COPY config /home/clowder/config
ENTRYPOINT ["/home/clowder/entrypoint.sh"]
CMD ["extractor"]
