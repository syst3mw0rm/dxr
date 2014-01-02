// A simple rust project

mod sub {
    pub mod sub2 {
        pub fn hello() {
            println("hello from a module");
        }
    }
}

fn hello() {
  let x: u32 = 5;
  println(x.to_str());
}

fn main() {
  hello();
  sub::sub2::hello();
}
