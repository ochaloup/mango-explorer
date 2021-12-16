from .datasaver import DataSaver

ds = DataSaver('/tmp/test.datasaver.data')

def do_something():
    for i in range(0,30):
        ds.publisher.publish(i)


if __name__ == '__main__':
    do_something()
