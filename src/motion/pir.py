import logging

logger = logging.getLogger(__name__)


class PIRSensor:
    """HC-SR501 PIR sensor via GPIO interrupt.

    RPi.GPIO is imported lazily in start() so this module loads cleanly
    on non-Pi development machines.
    """

    def __init__(self, pin: int, bouncetime: int = 300):
        self._pin = pin
        self._bouncetime = bouncetime
        self._gpio = None

    def start(self, callback) -> None:
        """Begin listening for motion events; calls callback(channel) on RISING edge."""
        import RPi.GPIO as GPIO

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._pin, GPIO.IN)
        GPIO.add_event_detect(
            self._pin,
            GPIO.RISING,
            callback=callback,
            bouncetime=self._bouncetime,
        )
        logger.debug("PIR listening on BCM pin %d (bouncetime=%dms)", self._pin, self._bouncetime)

    def stop(self) -> None:
        if self._gpio is None:
            return
        self._gpio.remove_event_detect(self._pin)
        self._gpio.cleanup(self._pin)
        self._gpio = None
        logger.debug("PIR stopped")
