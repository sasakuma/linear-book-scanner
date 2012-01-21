#!/usr/bin/python2.6
#
# Copyright 2011 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import glob
import pygame
import sys
import os.path
import urllib2
import BaseHTTPServer
import mmap
import cStringIO
import base64

paused = False           # For image inspection
image_number = 1         # Scanimage starts counting at 1
book_dimensions = None   # (top, bottom, side) in pixels
fullscreen = True        # Easier to debug in a window

def blue():
  """Original scansation blue, handed down from antiquity"""
  return (70, 120, 173)

def clearscreen(screen):
  """And G-d said, "Let there be blue light!"""
  screen.fill(blue())

def render_text(screen, msg, position):
  """Write messages to screen, such as the image number."""
  pos = [0, 0]
  font = pygame.font.SysFont('Courier', 28, bold=True)
  for line in msg.split("\n"):
    text = font.render(line, 1, (255, 255, 255))
    background = pygame.Surface(text.get_size())
    background.fill(blue())
    if position == "upperright":
      pos[0] = screen.get_width() - text.get_width()
    screen.blit(background, pos)
    screen.blit(text, pos)
    pos[1] += 30

def read_ppm_header(fp):
  """Read dimensions and headersize from a PPM file."""
  headersize = 0
  magic_number = fp.readline()
  if magic_number != "P6\n":
    raise TypeError("Hey! Not a ppm image file.")
  headersize += len(magic_number)
  comment = fp.readline()
  if comment[0] == "#":
    headersize += len(comment)
    dimensions = fp.readline()
  else:
    dimensions = comment
  headersize += len(dimensions)
  max_value = fp.readline()
  if max_value != "255\n":
    raise ValueError("I only work with 8 bits per color channel")
  headersize += len(max_value)
  w = int(dimensions.split(" ")[0])
  h = int(dimensions.split(" ")[1])
  return (w, h), headersize

def scale_to_crop_coord(scale_coord, scale_size, crop_size, epsilon):
  """Scale images are displayed 2-up in the screen."""
  w2 = pygame.display.Info().current_w // 2
  if scale_coord[0] < w2:
    x0 = w2 - epsilon - scale_size[0]
    is_left = True
  else:
    x0 = w2 + epsilon
    is_left = False
  x = (scale_coord[0] - x0) * crop_size[0] // scale_size[0]
  y = scale_coord[1] * crop_size[1] // scale_size[1]
  if is_left:
    x = crop_size[0] - x
  return (x, y), is_left

def crop_to_full_coord(crop_coord, is_left):
  """We always crop out saddle, and usually crop to book page."""
  x, y = crop_coord
  if book_dimensions:
    (top, bottom, side) = book_dimensions
    y += top
  if is_left:
    y += 593
  else:
    y += 150
  return x, y

def process_image(h, filename, is_left):
  """Return both screen resolution and scan resolution images."""
  kSaddleHeight = 3600  # scan pixels
  f = open(filename, "r+b")
  dimensions, headersize = read_ppm_header(f)
  map = mmap.mmap(f.fileno(), 0)
  image = pygame.image.frombuffer(buffer(map, headersize), dimensions, 'RGB')
  unused, y = crop_to_full_coord((0, 0), is_left)
  if book_dimensions:
    (top, bottom, side) = book_dimensions
    wh = (side, bottom - top)
  else:
    wh = (image.get_width(), kSaddleHeight)
  rect = pygame.Rect((0, y), wh)
  crop = image.subsurface(rect)
  w = image.get_width() * h // kSaddleHeight
  scale = pygame.transform.smoothscale(crop, (w, h))
  if is_left:
    scale = pygame.transform.flip(scale, True, False)
  return scale, crop

def clip_image_number(playground):
  """Only show images that exist."""
  global image_number
  if image_number < 1:
    image_number = 1
  while image_number > 1:
    filename = '%s/%06d.pnm' % (playground, image_number)
    if os.path.exists(filename):
      break
    image_number -= 2

def get_book_dimensions(playground):
  """User saved book dimensions in some earlier run."""
  global book_dimensions
  try:
    for line in open(os.path.join(playground, "book_dimensions")).readlines():
      if line[0] != "#":
        book_dimensions = [int(x) for x in line.split(",")]
  except IOError:
    pass

def set_book_dimensions(click, epsilon, crop_size, scale_size, playground):
  """User has dragged mouse to specify book position in image."""
  global book_dimensions
  down = list(click[0])
  up = list(click[1])
  filename = os.path.join(playground, "book_dimensions")
  min_book_dimension = 30  # screen pixels
  if book_dimensions == None:
    w2 = pygame.display.Info().current_w // 2
    down[0] = abs(w2 - down[0]) + w2
    up[0] =  abs(w2 - up[0]) + w2
    if min(abs(down[1] - up[1]), abs(up[0] - w2)) < min_book_dimension:
      return
    side = max(down[0], up[0]) - w2 - epsilon
    top = min(down[1], up[1])
    bottom = max(down[1], up[1])
    side = side * crop_size[0] // scale_size[0]
    top = top * crop_size[1] // scale_size[1]
    bottom = bottom * crop_size[1] // scale_size[1]
    book_dimensions = (top, bottom, side)
    f = open(filename, "wb")
    f.write("#top,bottom,side\n%s,%s,%s\n" % book_dimensions)
    f.close()
  else:
    book_dimensions = None
    os.unlink(filename)

def zoom(screen, click, epsilon, scale_a, scale_b, crop_a, crop_b):
  """Given a mouseclick, zoom in on the region."""
  coord, is_left = scale_to_crop_coord(click, scale_a.get_size(),
                                       crop_a.get_size(), epsilon)
  if is_left:
    crop = crop_a
  else:
    crop = crop_b
  size = pygame.display.Info().current_w // 3
  dst = (click[0] - size, click[1] - size)
  rect = pygame.Rect((coord[0] - size, coord[1] - size), (2 * size, 2 * size))
  if is_left:
    tmp = pygame.Surface((2 * size, 2 * size))
    tmp.blit(crop, (0,0), rect)
    tmp2 = pygame.transform.flip(tmp, True, False)
    screen.blit(tmp2, dst)
  else:
    screen.blit(crop, dst, rect)

def draw(screen, image_number, scale_a, scale_b, epsilon, paused):
  """Draw the page images on screen."""
  (w, h) = screen.get_size()
  render_text(screen, "%d           " % image_number, "upperleft")
  render_text(screen, "           %d" % (image_number + 1), "upperright")
  screen.blit(scale_a, (w // 2 - scale_a.get_width() - epsilon, 0))
  screen.blit(scale_b, (w // 2 + epsilon, 0))
  if paused:
    render_text(screen, "**  pause  **", "upperleft")

def save(crop_a, crop_b, playground, image_number):
  """Save cropped images in reading order."""
  global book_dimensions
  if book_dimensions is None:  # the book is not cropped
    return
  try:
    os.mkdir(os.path.join(playground, 'export'))
  except OSError:
    pass
  filename_a = '%s/export/%06d.jpg' % (playground, 999999 - image_number + 1)
  filename_b = '%s/export/%06d.jpg' % (playground, 999999 - image_number)
  a = pygame.transform.flip(crop_a, True, False)
  pygame.image.save(crop_b, filename_a)
  pygame.image.save(a, filename_b)

def get_bibliography(barcode):
  """Hit up Google Books for bibliographic data. Thanks, Leonid."""
  if barcode[0:3] == "978":
    url = ("http://books.google.com/books/download/"
           "?vid=isbn%s&output=enw&source=cheese" % barcode[0:13])
    try:
      bib = urllib2.urlopen(url, None, 2).read()
    except urllib2.URLError, e:
      if hasattr(e, 'reason'):
        excuse =  e.reason
      elif hasattr(e, 'code'):
        excuse = "HTTP return code %d\n" % e.code
        excuse += BaseHTTPServer.BaseHTTPRequestHandler.responses[e.code][0]
      return "Error looking up barcode: %s\n\n%s" % (barcode.split("_")[0],
                                                     excuse)
    return bib
  return "Unknown Barcode: %s" % barcode.split("_")[0]

def splashscreen(screen, barcode):
  """Like opening credits in a movie, but more useful."""
  clearscreen(screen)
  render_text(screen, "Looking up barcode: %s" % barcode.split("_")[0],
              "upperleft")
  pygame.display.update()
  clearscreen(screen)
  render_text(screen, get_bibliography(barcode), "upperleft")
  render_text(screen, ("\n\n\n\n\n\n\n\n\n\n"
                       "H,?         = help\n"
                       "MOUSE       = crop | mosaic | zoom\n"
                       "ARROWS      = navigation\n"
                       "PgUp/PgDn   = navigation!\n"
                       "\n"
                       "S           = screenshot\n"
                       "F11         = fullscreen\n"
                       "Q,ESC       = quit\n"
                       ), "upperleft")
  pygame.display.update()
  clearscreen(screen)
  pygame.time.wait(2000)

def handle_key_event(screen, event, playground, barcode, mosaic_click):
  """I found it easier to deal with keystrokes (mostly) in one place."""
  global image_number
  global paused
  global fullscreen
  newscreen = None
  if event.key == pygame.K_ESCAPE or event.key == pygame.K_q:
    pygame.quit()
    sys.exit()
  elif event.key == pygame.K_SPACE:
    if paused:
      paused = False
      return newscreen
  paused = True
  if event.key == pygame.K_F11:
    (w, h) = screen.get_size()
    if fullscreen:
      window = pygame.display.set_mode((w, h))
    else:
      window = pygame.display.set_mode((w, h), pygame.FULLSCREEN)
    fullscreen = not fullscreen
    newscreen = pygame.display.get_surface()
  elif event.key == pygame.K_LEFT or event.key == pygame.K_UP:
    image_number -= 2
  elif event.key == pygame.K_PAGEUP:
    image_number -= 10
  elif event.key == pygame.K_RIGHT or event.key == pygame.K_DOWN:
    image_number += 2
  elif event.key == pygame.K_PAGEDOWN:
    image_number += 10
  elif event.key == pygame.K_s:
    filename = "screenshot-" + barcode + "-" + str(image_number) + ".jpg"
    pygame.image.save(screen, filename);
    render_text(screen, filename, "upperright")
    pygame.display.update()
    pygame.time.wait(2000)
  elif event.key == pygame.K_h or event.key == pygame.K_QUESTION:
    splashscreen(screen, barcode)
    pygame.time.wait(3000)
  clip_image_number(playground)
  if mosaic_click:
    clearscreen(screen)
  return newscreen

def render(playground, h, screen, epsilon, paused, image_number):
  """Render and entire screen, including book images and labels."""
  filename_a = '%s/%06d.pnm' % (playground, image_number)
  filename_b = '%s/%06d.pnm' % (playground, image_number + 1)
  scale_a, crop_a = process_image(h, filename_a, True)
  scale_b, crop_b = process_image(h, filename_b, False)
  draw(screen, image_number, scale_a, scale_b, epsilon, paused)
  pygame.display.update()
  save(crop_a, crop_b, playground, image_number)
  return crop_a, crop_b, scale_a, scale_b, image_number

def mosaic_dimensions(screen):
  """Reduce some cut-n-past code. Everyone still assumes 20x20 mosaic."""
  n = 10
  size = (screen.get_height() // n, screen.get_height() // (2 * n))
  windowsize = 4 * n * n
  start = max(1, image_number - windowsize + 2)
  return size, windowsize, start

def navigate_mosaic(playground, screen, click):
  """Click on a mosaic tile, jump to that page."""
  global image_number
  clearscreen(screen)
  size, windowsize, start = mosaic_dimensions(screen)
  if click[0] > 10 * size[0]:
    return
  x, y = click[0] // size[0], click[1] // size[1]
  candidate = start + 2 * (10 * y + x)
  filename = '%s/%06d.pnm' % (playground, candidate)
  if os.path.exists(filename):
    image_number = candidate

def render_mosaic(screen, playground, click, scale_size, crop_size, epsilon,
                  image_number):
  """Useful for seeing lots of page numbers at once."""
  crop_coord, is_left = scale_to_crop_coord(click, scale_size,
                                            crop_size, epsilon)
  full_coord = crop_to_full_coord(crop_coord, is_left)
  size, windowsize, start = mosaic_dimensions(screen)
  if not is_left:
    start += 1
  for i in range(start, start + windowsize, 2):
    x = ((i - start) // 2) % 10
    y = (i - start) // 20
    filename = os.path.join(playground, '%06d.pnm' % i)
    if not os.path.exists(filename):
      break
    f = open(filename, "r+b")
    map = mmap.mmap(f.fileno(), 0)
    dimensions, headersize = read_ppm_header(f)
    image = pygame.image.frombuffer(buffer(map, headersize), dimensions, 'RGB')
    src = full_coord[0] - 3 * size[0] // 2, full_coord[1] - 3 * size[1] // 2
    rect = pygame.Rect(src, (size[0] * 3, size[1] * 3))
    crop = image.subsurface(rect)
    scale = pygame.transform.smoothscale(crop, size)
    if is_left:
      scale = pygame.transform.flip(scale, True, False)
    dst = (size[0] * x, size[1] * y)
    dirty = pygame.Rect(dst, size)
    screen.blit(scale, dst)
    map.close()
    f.close()
    pygame.display.update(dirty)

def get_beep():
  """Not having as external file makes life easier for sysadmins."""
  wav = """
UklGRigCAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQQCAAA01jVaF1f2WGJW1FoN
U5hhMcMxoKCoiqhcogiwOJTK/zxqak9fXHxWrFYcXv08rZtQrhShk6wBoXaudZtGPcZdBlcnVqdc
N09Tatf//pN7sKKhmKkypwui3sBzZJhP+V5tUfBeq09XZALB36Fnp1mp7KEksGWUXv/eappOVV1n
VdhX41w7Pm6ai6/hn7yt5Z+Cr3uaLD71XMJXgVU4XbpOu2qE/z2UT7C9oYupM6cVosvAjGR5Tx9f
QVEgX3hPimTQwA+iOqeEqcKhS7BBlIH/vmq2TjxdfVXGV/FcMD53moWv45+8reOfhq92mjE+71zI
V3xVPF22Tr9qf/9ClEuwwqGFqTinEKLQwItkd08gX0JRHl96T4pkzsASojenhanDoUuwQJSC/7xq
uE48XXxVx1fxXC4+epqCr+afuq3kn4Wvd5oxPu9cx1d9VTtduE6+an7/RZRGsMihfqk/pwui1MCG
ZHxPG19HURpffU+HZNHAEKI4p4apwKFPsDuUh/+2asJOLl2NVbNXBV0cPouaca/5n6Wt+p9wr4ma
Ij77XMFXfFVDXalO0mpm/2OUILD2oUipgKe+oSzBImTtT6FeyFGTXghQ+mNgwYGhw6cCqTmi5K+W
lED/5WqsTiddtVVnV3pdej1bm3OuJKFNrH+hv61knCI8GF+PVbVXG1uUUIZp4f4=
"""
  f = cStringIO.StringIO(base64.decodestring(wav))
  return pygame.mixer.Sound(f)

def main(argv1):
  """Display scanned images as they are created."""
  playground_dir, barcode = os.path.split(argv1)
  print playground_dir
  if not playground_dir:
    playground_dir = "/var/tmp/playground/"
  playground = os.path.join(playground_dir, barcode)
  pygame.init()
  global image_number
  global paused
  global book_dimensions
  last_drawn_image_number = 0
  get_book_dimensions(playground)
  beep = get_beep()
  h = pygame.display.Info().current_h
  w = pygame.display.Info().current_w
  epsilon = w // 100
  window = pygame.display.set_mode((w, h), pygame.FULLSCREEN)
  screen = pygame.display.get_surface()
  pygame.display.set_caption("Barcode: %s" % barcode)
  splashscreen(screen, barcode)
  pygame.time.set_timer(pygame.USEREVENT, 50)
  shadow = pygame.Surface(screen.get_size())
  shadow.set_alpha(128)
  shadow.fill((0, 0, 0))
  mosaic_click = None  # Don't mode me in, bro!
  busy = False
  while True:
    for event in [ pygame.event.wait() ]:
      if event.type == pygame.MOUSEBUTTONDOWN:
        busy = True
        pygame.event.clear(pygame.USEREVENT)
      if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        if mosaic_click:
          continue
        leftdownclick = event.pos
        oldscreen = screen.copy()
        shadowscreen = screen.copy()
        shadowscreen.blit(shadow, (0, 0))
        screen.blit(shadowscreen, (0, 0))
        prevroi = pygame.Rect(event.pos, (0, 0))
        pygame.display.update()
      elif event.type == pygame.MOUSEMOTION and event.buttons[0] == 1:
        if book_dimensions or mosaic_click:
          continue
        x = abs(event.pos[0] - w // 2)
        pos = (w // 2 - x, min(leftdownclick[1], event.pos[1]))
        roi = pygame.Rect(pos, (2 * x, abs(leftdownclick[1] - event.pos[1])))
        dirty = roi.union(prevroi)
        prevroi = roi.copy()
        screen.blit(shadowscreen, dirty.topleft, area = dirty)
        screen.blit(oldscreen, roi.topleft, area = roi)
        pygame.display.update(dirty)
      elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        if mosaic_click:
          navigate_mosaic(playground, screen, event.pos)
          last_drawn_image_number = None
          mosaic_click = None
        else:
          oldscreen = None
          leftclick = (leftdownclick, event.pos)
          set_book_dimensions(leftclick, epsilon, crop_a.get_size(),
                              scale_a.get_size(), playground)
          clearscreen(screen)
          crop_a, crop_b, scale_a, scale_b, last_drawn_image_number = \
              render(playground, h, screen, epsilon, paused, image_number)
        busy = False
      elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
        draw(screen, image_number, scale_a, scale_b, epsilon, paused)
        zoom(screen, event.pos, epsilon, scale_a, scale_b, crop_a, crop_b)
        pygame.display.update()
      elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
        mosaic_click = None
        clearscreen(screen)
        draw(screen, image_number, scale_a, scale_b, epsilon, paused)
        pygame.display.update()
        busy = False
      elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
        mosaic_click = event.pos
        if image_number != last_drawn_image_number:
          crop_a, crop_b, scale_a, scale_b, last_drawn_image_number = \
              render(playground, h, screen, epsilon, paused, image_number)
        render_mosaic(screen, playground, mosaic_click, scale_a.get_size(),
                      crop_a.get_size(), epsilon, image_number)
        paused = True
        busy = False
      elif event.type == pygame.QUIT:
        pygame.quit()
        sys.exit()
      elif mosaic_click and \
            event.type == pygame.KEYDOWN and \
            (event.key == pygame.K_PAGEUP or event.key == pygame.K_PAGEDOWN):
        size, windowsize, start = mosaic_dimensions(screen)
        if event.key == pygame.K_PAGEUP:
          image_number = start - 2
        elif event.key == pygame.K_PAGEDOWN:
          image_number = start + windowsize + windowsize - 2
        clip_image_number(playground)
        if image_number != last_drawn_image_number:
          crop_a, crop_b, scale_a, scale_b, last_drawn_image_number = \
              render(playground, h, screen, epsilon, paused, image_number)
        render_mosaic(screen, playground, mosaic_click, scale_a.get_size(),
                      crop_a.get_size(), epsilon, image_number)
      elif event.type == pygame.KEYDOWN:
        newscreen = handle_key_event(screen, event, playground, barcode,
                                     mosaic_click)
        mosaic_click = None
        if newscreen:
          screen = newscreen
        draw(screen, image_number, scale_a, scale_b, epsilon, paused)
        pygame.display.update()
      elif event.type == pygame.USEREVENT:
        if busy:
          continue
        if not paused:
          image_number += 2
          clip_image_number(playground)
        if image_number != last_drawn_image_number:
          try:
            crop_a, crop_b, scale_a, scale_b, last_drawn_image_number = \
                render(playground, h, screen, epsilon, paused, image_number)
            if not paused:
              beep.play()
          except pygame.error:
            pass
          pygame.event.clear(pygame.USEREVENT)

if __name__ == "__main__":
  main(sys.argv[1])
