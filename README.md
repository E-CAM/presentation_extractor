This is a [Clowder](https://clowder.ncsa.illinois.edu) extractor for the video recording of a presentation.
It will try to detect any slide transition and store those locations in the JSON-LD metadata. Of every slide
a preview is also created and upload to Clowder.

# How does it detect slide transitions?

The extractor uses OpenCV to iterate through all frames in the video. To detect slide changes, it can use two
algorithms:
  - basic: Every frame is converted to gray scale and then compared to the previous frame. If enough pixels
    have changed 'significantly' we assume a new slide is shown.
  - advanced: The algorithm leverages motion tracking techniques and works well with unprocessed screen
    capture (heavy compression can introduce false positives).

advanced is the default algorithm. Both have multiple parameters that can be tuned. Read the `settings.yml` file
to get an overview. Each parameter can be tuned by user passed JSON in Clowder.

# Override default parameters

If you submit a file manually to an extractor in Clowder, a set of parameters can be passed on (in JSON). You can use
this to pass maskings settings or parameters changes. For example:
```json
{
    "slides": {
        "minimum_slide_length": 15
    }
}
```

# Metadata format

The metadata looks like:
```json
{
    "listslides": [("00:00:00.000", "00:00:08.433", "5a0a048de4b03bcb94a73ba8"), ...],
    "nrslides": 7,
    "algorithm": "advanced",
    "settings": { <extractor settings> }
}
```
`listslides` is a list containing begin and end time of a slide with the id of the preview of that slide.

# Docker

This extractor is ready to be run as a docker container. To build the docker container run:

```
docker build -t clowder_videopresentation .
```

To run the docker containers use:

```
docker run -t -i --rm -e "RABBITMQ_URI=amqp://rabbitmqserver/clowder" clowder_videopresentation
docker run -t -i --rm --link clowder_rabbitmq_1:rabbitmq clowder_videopresentation
```

The RABBITMQ_URI and RABBITMQ_EXCHANGE environment variables can be used to control what RabbitMQ server and exchange it will bind itself to, you can also use the --link option to link the extractor to a RabbitMQ container.
