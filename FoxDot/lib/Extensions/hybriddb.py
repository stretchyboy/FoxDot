from pony.orm import *
from music21 import pitch
import os
from shutil import copyfile
import re
notefilenamepattern = re.compile("([a-gA-G][\_\-\+\b\#\^]*(10|[0-9]))|((10|[0-9])[a-gA-G][\_\-\+\b\# ]*)")

db = Database()
#set_sql_debug(True)

# Use the homefolder so we know where everything is
basefolder = os.path.join(os.path.expanduser("~"),".foxdot_samples")
if not os.path.exists(basefolder):
    os.makedirs(basefolder)

db.bind(provider='sqlite', filename=os.path.join(basefolder, 'database.sqlite'), create_db=True)

def getMidiByName(note, oct=4):
    fullnote = notename+str(octave)
    try:
        p = pitch.Pitch(fullnote)
        return p.midi
    except(pitch.AccidentalException, pitch.PitchException) as err:
        print("Cannot make note from " + fullnote)
        return None

class Tone(db.Entity):
    id          = PrimaryKey(int, auto=True)
    name        = Required(str)
    samples     = Set('Sample')
    notes_map   = Optional(Json)
    samples_map = Optional(Json)

    def getFolderPath(self):
        dir = "".join(x for x in self.name if x.isalnum())
        directory = os.path.join(os.path.expanduser("~"),".foxdot_samples", dir)
        if not os.path.exists(directory):
            os.makedirs(directory)
        return directory

    def getSampleIDs(self):
        return self.samples_map

    #cache the FoxDot best sample ids and player rate for each midi note
    def makeMap(self):
        map = {}
        for midi in range(0,120):
            #loop around samples
            lowscore = 1000000000
            lowsample = None
            for s in self.samples:
                currscore = s.score(midi)
                #print("currscore", currscore,lowscore)
                if(currscore < lowscore):
                    lowscore = currscore
                    lowsample = s
            if(lowsample):
                transform = lowsample.getTransform(midi)
                map[midi] = (lowsample.get_pk(), transform)
            else:
                map[midi] = (None, None)

        self.notes_map = map
        samples = []
        for s in self.samples:
            samples.append(s.get_pk())
        self.samples_map = samples


    def getClosestSample(self, midi):
        sampleid, transform = self.notes_map[midi]
        if(sampleid):
            return Sample[sampleid]
        return False

    def getNotePlayInfo(self, midi):
        sampleid, transform = self.notes_map[midi]
        if(sampleid):
            return (sampleid, transform)
        return False

def getFileName(name, sample=0):
    return '{0:03d}_'.format(sample)+name
    #return '{0:03d}_'.format(sample)+("".join(x for x in name if x.isalnum()).lower()) + ".wav"


def getNoteFromWavFile(filename, samplerate = 44100):
    from aubio import source, pitch, midi2note
    from numpy import mean, array, ma

    try:
        downsample = 1
        win_s = 4096 // downsample # fft size
        hop_s = 512  // downsample # hop size

        s = source(filename, samplerate, hop_s)
        samplerate = s.samplerate

        tolerance = 0.8

        pitch_o = pitch("yin", win_s, hop_s, samplerate)
        pitch_o.set_unit("midi")
        pitch_o.set_tolerance(tolerance)

        pitches = []
        confidences = []

        # total number of frames read
        total_frames = 0
        while True:
            samples, read = s()
            pitch = pitch_o(samples)[0]
            #pitch = int(round(pitch))
            confidence = pitch_o.get_confidence()
            #if confidence < 0.8: pitch = 0.
            #print("%f %f %f" % (total_frames / float(samplerate), pitch, confidence))
            pitches += [pitch]
            confidences += [confidence]
            total_frames += read
            if read < hop_s: break



        #print pitches

        skip = 1

        pitches = array(pitches[skip:])
        confidences = array(confidences[skip:])

        # plot cleaned up pitches
        cleaned_pitches = pitches
        #cleaned_pitches = ma.masked_where(cleaned_pitches < 0, cleaned_pitches)
        #cleaned_pitches = ma.masked_where(cleaned_pitches > 120, cleaned_pitches)
        cleaned_pitches = ma.masked_where(confidences < tolerance, cleaned_pitches)
        cleaned_pitches = ma.masked_where(cleaned_pitches==0, cleaned_pitches)
        note = int(round(mean(cleaned_pitches.compressed())))

        print(note, midi2note(note))

        return note
    except RuntimeError as err:
        print ("Could not find note from WAV "+ filename)
        print (err)
        return None

def getNoteFromFileName(filename):
    #print("getNoteFromFileName", filename)
    result = notefilenamepattern.search(filename)

    if result == None:

        return None
    #print("result", result.group(0))
    fullnote = result.group(0)

    try:
        p = pitch.Pitch(fullnote)
        return p.midi
    except(pitch.AccidentalException, pitch.PitchException) as err:
        print("Cannot make note from " + fullnote)
        return None

    return None


class Sample(db.Entity):
    id      = PrimaryKey(int, auto=True)
    name    = Required(str)
    filename= Required(str)
    sample  = Required(int)
    tone    = Required(Tone)
    length  = Optional(int)
    bpm     = Optional(int)
    midi    = Required(int)
    notes   = Set('Note')
    source  = Optional(str)
    samplerate= Required(int, default=44100)


    def score(self, midi):
        densityscore = 0
        #if the note we have is higher than what we want to play
        #the it is a little bit worse than the lower one at the same distance
        pitchSelf = pitch.Pitch(midi = self.midi)
        pitchMidi = pitch.Pitch(midi = midi)
        if( pitchSelf > pitchMidi):
            densityscore = 1
        return densityscore + round(100*pitchMidi.frequency / pitchSelf.frequency)

    # the ratio to play the note at to get what we want
    def getTransform(self, midi):
        pitchSelf = pitch.Pitch(midi = self.midi)
        pitchMidi = pitch.Pitch(midi = midi)
        return pitchMidi.frequency / pitchSelf.frequency

    def __init__(self,
        inputfilepath   = None,
        tone            = None,
        bpm             = None,
        midi            = None,
        notename        = None,
        octave          = None,
        source          = None,
        samplerate      = None
     ):

        name = os.path.basename(inputfilepath)
        #samples = Sample.select(tone=tone).count()
        sample = select(s for s in Sample if s.tone == tone).count()

        #print("sample", sample)
        filename = getFileName(name, sample)
        #print("filename", filename)

        if(notename and octave):
            midi = getMidiByName(notename, oct=4)

        super().__init__(
            tone    = tone,
            name    = name,
            midi    = midi,
            bpm     = bpm,
            sample  = sample,
            filename= filename,
            source  = source,
            samplerate = samplerate
            )

        dir = tone.getFolderPath()
        path = os.path.join(dir, filename)
        copyfile(inputfilepath, path)

    def after_delete(self):
        self.tone.makeMap()

    def after_insert(self):
        self.tone.makeMap()

    def after_update():
        self.tone.makeMap()

class Note(db.Entity):
    id          = PrimaryKey(int, auto=True)
    sample      = Required(Sample)
    startatbeat = Required(int)
    endatbeat   = Required(int)
    midi        = Required(int)


db.generate_mapping(create_tables=True)


@db_session
def get_or_create_tone(name):
    if Tone.exists(name=name):
        return Tone.get(name=name)
    return Tone(name=name)

@db_session
def get_tone(name):
    if(isinstance(name, int)):
        if Tone.exists(id=name):
            return Tone.get(id=name)
        return None

    if Tone.exists(name=name):
        return Tone.get(name=name)
    return None

@db_session
def show_list():
    select((t.id, t.name) for t in Tone).show()

@db_session
def get_list():
    strs = []
    for t in select(t for t in Tone):
        strs.append(str(t.id) + ": " + t.name)
    return os.linesep.join(strs)

@db_session
def refresh():
    for t in select(t for t in Tone):
        t.makeMap()


@db_session
def get_or_create_tone_from_sample(
    inputfilepath=None,
    bpm = None,
    midi = None,
    notename = None,
    octave = None,
    source = None,
    samplerate = 44100,
    ):

    tonefolderpath = os.path.dirname(inputfilepath)
    tonefolder = os.path.basename(tonefolderpath)
    #print("tonefolder", tonefolder)

    t = get_or_create_tone(tonefolder)
    s = get_or_create_sample(
        inputfilepath=inputfilepath,
        tone=t,
        bpm = bpm,
        midi = midi,
        notename = notename,
        octave = octave,
        source = source,
        samplerate = samplerate,
        )

    #t.makeMap()

    return t,s

@db_session
def get_or_create_sample(
    inputfilepath=None,
    tone=None,
    bpm = None,
    midi = None,
    notename = None,
    octave = None,
    source = None,
    samplerate = 44100,
    ):

    if(notename and octave):
        midi = getMidiByName(notename, oct=4)

    if midi == None:
        midi = getNoteFromFileName(inputfilepath)

    if midi == None:
        midi = getNoteFromWavFile(inputfilepath,samplerate)

    if midi == None:
        print("Cannot find Note info for "+inputfilepath)
        fullnote = input("Please enter the Note (A2 c#4 etc.) (empty to skip): ")
        if fullnote:
            try:
                p = pitch.Pitch(fullnote)
                midi = p.midi
            except(pitch.AccidentalException, pitch.PitchException) as err:
                print("Cannot make note from " + fullnote)
                return None

    if midi == None:
        raise ValueError("Cannot find Midi Note for "+inputfilepath)
        return None

    if Sample.exists(tone=tone, midi=midi):
        return Sample.get(tone=tone, midi=midi)

    return Sample(
        inputfilepath=inputfilepath,
        tone=tone,
        bpm = bpm,
        midi = midi,
        notename = notename,
        octave = octave,
        source = source,
        samplerate = samplerate
        )

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Load Samplesfor FoxDot.'
        )
    parser.add_argument('-p','--path', nargs='?', metavar='PATH', type=str,
                        help='inputfilepath')
    #parser.add_argument('-f','--file', nargs='?', type=argparse.FileType('r'),
    #                 default=sys.stdin)

    parser.add_argument('-b','--bpm', type=int, nargs='?', default=110,
                        help='BPM of sample')

    parser.add_argument('-n','--note', type=str, nargs='?', default=None,
                        help='Note name of sample')

    parser.add_argument('-o','--octave', type=int, nargs='?', default=None,
                        help='Octave of sample')

    parser.add_argument('-m','--midi', type=int, nargs='?', default=None,
                        help='Midi number of sample')

    parser.add_argument('-s','--source', type=str, nargs='?', default="",
                        help='Source of sample')

    parser.add_argument('-e','--samplerate', type=int, nargs='?', default=44100,
                        help='Sample Rate of sample')

    parser.add_argument('-d','--delete', type=int, nargs='?', default=None,
                        help='Delete a Tone')

    parser.add_argument('-t','--test', action='store_true', help="Run test suite")
    parser.add_argument('-l','--list', action='store_true', help="List available tones")
    parser.add_argument('-r','--refresh', action='store_true', help="Regenerate Mapping Data")

    # DONE: add -t for test
    # DONE: add -l for list get_or_create_tone_from_sample

    args = parser.parse_args()


    if(args.path):
        ourtone=None
        if os.path.isdir(args.path):
            for entry in os.listdir(args.path):
                fullpath = os.path.join(args.path, entry)
                if os.path.isfile(fullpath) and entry.endswith('.wav'):
                    with db_session:
                        try:
                            t, s = get_or_create_tone_from_sample(
                                inputfilepath = os.path.abspath(fullpath),
                                bpm=args.bpm,
                                source = args.source,
                                samplerate = args.samplerate
                            )
                            ourtone = t
                        except ValueError as err:
                            print (err)

            else :
                with db_session:
                    try:
                        t, s = get_or_create_tone_from_sample(
                            inputfilepath = os.path.abspath(args.path),
                            bpm=args.bpm,
                            notename = args.note,
                            octave = args.octave,
                            midi=args.midi,
                            source = args.source,
                            samplerate = args.samplerate
                        )
                    except ValueError as err:
                        print (err)

        if(ourtone):
            with db_session:
                print(ourtone.getNotePlayInfo(60))

    elif(args.delete):
        with db_session:
            t = get_tone(args.delete)
            t.delete()
            show_list()


    elif(args.test):
        with db_session:
            t, s = get_or_create_tone_from_sample(
                inputfilepath = "/home/meggleton/Downloads/Fingered (bridge pickup) Rickenbacker bass (4001 - 1974)/163021__project16__d-3-pp.wav",
                #notename = "D",
                #octave = 3
                source = "P: by Project16 -- https://freesound.org/people/Project16/packs/10106/"
                )

            t, s = get_or_create_tone_from_sample(
                inputfilepath = "/home/meggleton/Downloads/Fingered (bridge pickup) Rickenbacker bass (4001 - 1974)/162995__project16__f-3-pp.wav",
                #notename = "F",
                #octave = 3
                source = "P: by Project16 -- https://freesound.org/people/Project16/packs/10106/"
                )

            t, s = get_or_create_tone_from_sample(
                inputfilepath = "/home/meggleton/Downloads/Fingered (bridge pickup) Rickenbacker bass (4001 - 1974)/162969__project16__a2-pp.wav",
                #notename = "A",
                #octave = 2
                source = "P: by Project16 -- https://freesound.org/people/Project16/packs/10106/"
                )


            print("t.getNotePlayInfo(60)", t.getNotePlayInfo(60))

    elif(args.list):
        show_list()

    elif(args.refresh):
        refresh()

    else:
        parser.print_usage()

if __name__ == "__main__":
    main()
