# frozen_string_literal: true

Gem::Specification.new do |spec|
  spec.name          = "portfolio"
  spec.version       = "0.1.0"
  spec.authors       = ["Marshtupa Bogdan"]
  spec.email         = ["marshtupa18@gmail.com"]

  spec.summary       = "Portfolio"
  spec.homepage      = "https://github.com/marshtupa"
  spec.license       = "MIT"

  spec.files         = `git ls-files -z`.split("\x0").select { |f| f.match(%r!^(assets|_layouts|_includes|_sass|LICENSE|README)!i) }

  spec.add_runtime_dependency "jekyll"

  spec.add_development_dependency "bundler"
  spec.add_development_dependency "rake"
  spec.add_development_dependency "jekyll-paginate"
end
