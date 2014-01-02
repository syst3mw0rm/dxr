#[feature(managed_boxes, globs)];

extern mod rustc;
extern mod syntax;

use syntax::diagnostic::Emitter;

fn main() {
  println("rust-dxr started");

  /*let args = std::os::args().to_owned();
  let (p, ch) = std::comm::SharedChan::new();
  let demitter = @rustc::RustcEmitter {
      ch_capture: ch.clone(),
  } as @Emitter;
  rustc::run_compiler(args, demitter);*/
}
